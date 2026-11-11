from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from mandate_core.domain.errors import NotFoundError

from adapters.llm_astropods import AstropodsLLM
from adapters.notifier_console import WebhookNotifier
from adapters.partner_elastic import serialize_catalog_docs, serialize_ledger_docs
from apps.api.auth import require_user_auth
from apps.api.dependencies import AppContainer, get_container
from apps.api.schemas import (
    ElasticSyncResponse,
    IntegrationServiceStatus,
    IntegrationsStatusResponse,
    RenderWorkflowRunResponse,
    RenderWorkflowTriggerRequest,
    ZapierTestRequest,
    ZapierTestResponse,
)

router = APIRouter(prefix="/integrations", tags=["Integrations"])


def integration_flags(c: AppContainer) -> dict[str, bool]:
    s = c.settings
    return {
        "paypal": bool(s.paypal_mode in {"sandbox", "live"} and s.paypal_client_id and s.paypal_client_secret),
        "gemini": bool(s.gemini_api_key),
        "groq": bool(s.groq_api_key),
        "astropods": bool(s.astro_gateway_url and s.astro_gateway_api_key),
        "channel3": bool(s.catalog_provider == "channel3" and s.channel3_api_key),
        "kernel": c.kernel.is_live,
        "elastic": c.elastic.is_live,
        "render_workflows": c.render_workflows.is_live,
        "zapier": bool(s.zapier_webhook_url),
    }


@router.get("/status", response_model=IntegrationsStatusResponse)
async def integrations_status(
    probe: bool = False,
    container: AppContainer = Depends(get_container),
) -> IntegrationsStatusResponse:
    """Report configuration status (and optional live connectivity probe) for all partner APIs."""
    s = container.settings
    flags = integration_flags(container)

    kernel_probe: dict[str, Any] = {}
    elastic_probe: dict[str, Any] = {}
    render_probe: dict[str, Any] = {}
    astro_probe: dict[str, Any] = {}
    paypal_probe_ok: bool | None = None

    if probe:
        kernel_probe = await container.kernel.probe()
        elastic_probe = await container.elastic.probe()
        render_probe = await container.render_workflows.probe()
        if isinstance(container.llm, AstropodsLLM):
            astro_probe = await container.llm.probe()
        if flags["paypal"]:
            try:
                tok_fn = getattr(container.payment, "_get_access_token", None)
                if callable(tok_fn):
                    await tok_fn()
                    paypal_probe_ok = True
            except Exception:
                paypal_probe_ok = False

    services = [
        IntegrationServiceStatus(
            name="paypal",
            configured=flags["paypal"],
            mode=s.paypal_mode if flags["paypal"] else "mock",
            live_ok=paypal_probe_ok,
            details={"toolkit": "paypal-agent-toolkit", "webhook_id_set": bool(s.paypal_webhook_id)},
        ),
        IntegrationServiceStatus(
            name="gemini",
            configured=flags["gemini"],
            mode="live" if flags["gemini"] else "deterministic_fallback",
            details={"model": s.gemini_model, "active": s.llm_provider == "gemini" and flags["gemini"]},
        ),
        IntegrationServiceStatus(
            name="groq",
            configured=flags["groq"],
            mode="live" if flags["groq"] else "deterministic_fallback",
            details={"model": s.groq_model, "active": s.llm_provider == "groq" and flags["groq"]},
        ),
        IntegrationServiceStatus(
            name="astropods",
            configured=flags["astropods"],
            mode="live" if flags["astropods"] else "unconfigured",
            live_ok=astro_probe.get("ok") if probe and astro_probe else None,
            details={"model": s.astro_model, "active": s.llm_provider == "astropods" and flags["astropods"]},
        ),
        IntegrationServiceStatus(
            name="channel3",
            configured=flags["channel3"],
            mode="live" if flags["channel3"] else "mock_catalog",
            details={"catalog_provider": s.catalog_provider},
        ),
        IntegrationServiceStatus(
            name="kernel",
            configured=flags["kernel"],
            mode="live" if flags["kernel"] else "deterministic_fallback",
            live_ok=kernel_probe.get("ok") if probe else None,
            details={"endpoint": "POST /catalog/verify-url"},
        ),
        IntegrationServiceStatus(
            name="elastic",
            configured=flags["elastic"],
            mode="live" if flags["elastic"] else "deterministic_fallback",
            live_ok=elastic_probe.get("ok") if probe else None,
            details={"index_prefix": s.elastic_index_prefix},
        ),
        IntegrationServiceStatus(
            name="render_workflows",
            configured=flags["render_workflows"],
            mode="live" if flags["render_workflows"] else "simulated",
            live_ok=render_probe.get("ok") if probe else None,
            details={"task_slug": s.render_workflow_task_slug or "mandate-recheck/sweep"},
        ),
        IntegrationServiceStatus(
            name="zapier",
            configured=flags["zapier"],
            mode="webhook" if isinstance(container.notifier, WebhookNotifier) else "console",
            details={"notifier_provider": s.notifier_provider},
        ),
        IntegrationServiceStatus(
            name="ag_grid",
            configured=True,
            mode="ssrm",
            details={"endpoint": "GET /ledger"},
        ),
        IntegrationServiceStatus(
            name="bryntum",
            configured=True,
            mode="scheduler_json",
            details={"endpoints": ["GET /cases/timeline", "GET /mandates/schedule"]},
        ),
        IntegrationServiceStatus(
            name="postman_apimatic",
            configured=True,
            mode="openapi_3_1",
            details={"collection": "docs/mandate-postman-collection.json"},
        ),
    ]
    return IntegrationsStatusResponse(probed=probe, services=services)


@router.post(
    "/elastic/sync",
    response_model=ElasticSyncResponse,
    dependencies=[Depends(require_user_auth)],
)
async def sync_to_elastic(
    container: AppContainer = Depends(get_container),
) -> ElasticSyncResponse:
    """Index current catalog items and audit ledger entries into Elastic (or fallback index)."""
    products = await container.catalog.search("", limit=100)
    cat_res = await container.elastic.bulk_index("catalog", serialize_catalog_docs(products))

    entries = await container.store.iter_all_ledger()
    led_res = await container.elastic.bulk_index("ledger", serialize_ledger_docs(entries))

    return ElasticSyncResponse(
        mode=cat_res["mode"],
        catalog_indexed=cat_res["indexed"],
        ledger_indexed=led_res["indexed"],
        errors=bool(cat_res.get("errors") or led_res.get("errors")),
    )


@router.post(
    "/render/workflows/trigger",
    response_model=RenderWorkflowRunResponse,
    dependencies=[Depends(require_user_auth)],
)
async def trigger_render_workflow(
    body: RenderWorkflowTriggerRequest | None = None,
    container: AppContainer = Depends(get_container),
) -> RenderWorkflowRunResponse:
    """Trigger a Render Workflow sweep task (and optionally run local due recheck jobs)."""
    req = body or RenderWorkflowTriggerRequest()
    local_processed = 0
    if req.run_local_recheck:
        local_processed = await container.orchestrator.process_due_recheck_jobs(limit=10)

    run = await container.render_workflows.trigger_task(
        task_slug=req.task_slug,
        input_args=req.input_args,
        metadata={"local_recheck_jobs_processed": local_processed},
    )
    return RenderWorkflowRunResponse.model_validate(run)


@router.get(
    "/render/workflows/runs/{run_id}",
    response_model=RenderWorkflowRunResponse,
    dependencies=[Depends(require_user_auth)],
)
async def get_render_workflow_run(
    run_id: str,
    container: AppContainer = Depends(get_container),
) -> RenderWorkflowRunResponse:
    """Inspect a Render Workflow task run status."""
    run = await container.render_workflows.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Render workflow run {run_id} not found")
    return RenderWorkflowRunResponse.model_validate(run)


@router.post(
    "/zapier/test",
    response_model=ZapierTestResponse,
    dependencies=[Depends(require_user_auth)],
)
async def test_zapier_notifier(
    body: ZapierTestRequest | None = None,
    container: AppContainer = Depends(get_container),
) -> ZapierTestResponse:
    """Send a test notification through the active Notifier (Zapier webhook or Console)."""
    req = body or ZapierTestRequest()
    await container.notifier.notify(
        event=req.event,
        case_id=req.case_id,
        message=req.message,
        details=req.details,
    )
    mode = "webhook" if isinstance(container.notifier, WebhookNotifier) else "console"
    return ZapierTestResponse(delivered=True, mode=mode, event=req.event)
