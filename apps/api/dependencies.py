from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from mandate_core.commands import CommandRegistry
from mandate_core.domain.errors import NotFoundError
from mandate_core.ports import LLM, Catalog, Notifier, PaymentProvider
from mandate_core.statemachine import Orchestrator
from mandate_core.workflows import (
    RankedOption,
    build_proposal_from_product,
    compile_mandate_from_text,
    search_and_ask_preference,
)

from adapters.auth import GoogleIdentityVerifier, SmsOtpSender
from adapters.catalog_channel3 import Channel3Catalog
from adapters.catalog_mock import MockCatalog
from adapters.llm_astropods import AstropodsLLM
from adapters.llm_gemini import GeminiLLM
from adapters.llm_groq import GroqLLM
from adapters.notifier_console import ConsoleNotifier, WebhookNotifier
from adapters.partner_elastic import ElasticSearchAdapter
from adapters.partner_kernel import KernelVerifier
from adapters.partner_render import RenderWorkflowsClient
from adapters.paypal import MockPayPalProvider, PayPalPaymentProvider
from adapters.persistence import SqlAlchemyStateStore, create_engine_and_sessionmaker
from apps.api.config import Settings


@dataclass
class AppContainer:
    settings: Settings
    store: SqlAlchemyStateStore
    catalog: Catalog
    payment: PaymentProvider
    llm: LLM | None
    notifier: Notifier
    orchestrator: Orchestrator
    commands: CommandRegistry
    kernel: KernelVerifier
    elastic: ElasticSearchAdapter
    render_workflows: RenderWorkflowsClient
    google_verifier: GoogleIdentityVerifier
    sms_sender: SmsOtpSender
    last_options: list[RankedOption] = field(default_factory=list)


def build_container(
    settings: Settings,
    *,
    catalog: Catalog | None = None,
    payment: PaymentProvider | None = None,
    llm: LLM | None = None,
    notifier: Notifier | None = None,
    kernel: KernelVerifier | None = None,
    elastic: ElasticSearchAdapter | None = None,
    render_workflows: RenderWorkflowsClient | None = None,
    google_verifier: GoogleIdentityVerifier | None = None,
    sms_sender: SmsOtpSender | None = None,
) -> AppContainer:
    engine, session_factory = create_engine_and_sessionmaker(settings.database_url)
    store = SqlAlchemyStateStore(engine, session_factory)

    resolved_catalog: Catalog = catalog or (
        Channel3Catalog(api_key=settings.channel3_api_key)
        if settings.catalog_provider == "channel3" and settings.channel3_api_key
        else MockCatalog(
            seller_a_payee_id=settings.paypal_sandbox_seller_a_id,
            seller_b_payee_id=settings.paypal_sandbox_seller_b_id,
        )
    )

    if payment is not None:
        resolved_payment: PaymentProvider = payment
    elif settings.paypal_mode in {"sandbox", "live"} and settings.paypal_client_id and settings.paypal_client_secret:
        resolved_payment = PayPalPaymentProvider(
            client_id=settings.paypal_client_id,
            client_secret=settings.paypal_client_secret,
            sandbox=(settings.paypal_mode == "sandbox"),
            webhook_id=settings.paypal_webhook_id or None,
        )
    else:
        resolved_payment = MockPayPalProvider()

    resolved_llm: LLM | None = llm
    if resolved_llm is None:
        if settings.llm_provider == "gemini" and settings.gemini_api_key:
            resolved_llm = GeminiLLM(api_key=settings.gemini_api_key, model=settings.gemini_model)
        elif settings.llm_provider == "groq" and settings.groq_api_key:
            resolved_llm = GroqLLM(api_key=settings.groq_api_key, model=settings.groq_model)
        elif (
            settings.llm_provider == "astropods"
            and settings.astro_gateway_url
            and settings.astro_gateway_api_key
        ):
            resolved_llm = AstropodsLLM(
                gateway_url=settings.astro_gateway_url,
                api_key=settings.astro_gateway_api_key,
                model=settings.astro_model,
            )

    resolved_notifier: Notifier = notifier or (
        WebhookNotifier(settings.zapier_webhook_url)
        if settings.notifier_provider == "webhook" and settings.zapier_webhook_url
        else ConsoleNotifier()
    )

    resolved_kernel = kernel or KernelVerifier(
        api_key=settings.kernel_api_key,
        base_url=settings.kernel_base_url,
    )
    resolved_elastic = elastic or ElasticSearchAdapter(
        url=settings.elastic_url,
        api_key=settings.elastic_api_key,
        index_prefix=settings.elastic_index_prefix,
    )
    resolved_render = render_workflows or RenderWorkflowsClient(
        api_key=settings.render_api_key,
        api_base=settings.render_api_base,
        default_task_slug=settings.render_workflow_task_slug,
    )
    resolved_google = google_verifier or GoogleIdentityVerifier(
        client_id=settings.google_client_id,
        allow_demo_mode=settings.auth_allow_demo_mode,
    )
    resolved_sms = sms_sender or SmsOtpSender(
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_from_number,
    )

    orchestrator = Orchestrator(
        store=store,
        catalog=resolved_catalog,
        payment=resolved_payment,
        llm=resolved_llm,
        notifier=resolved_notifier,
    )

    container = AppContainer(
        settings=settings,
        store=store,
        catalog=resolved_catalog,
        payment=resolved_payment,
        llm=resolved_llm,
        notifier=resolved_notifier,
        orchestrator=orchestrator,
        commands=None,  # type: ignore[arg-type]
        kernel=resolved_kernel,
        elastic=resolved_elastic,
        render_workflows=resolved_render,
        google_verifier=resolved_google,
        sms_sender=resolved_sms,
    )

    async def _compile_and_draft(text: str, actor: str) -> dict[str, Any]:
        draft = await compile_mandate_from_text(text, owner_id=actor, llm=resolved_llm)
        saved = await orchestrator.create_mandate_draft(draft, actor=actor)
        return {"mandate": saved.model_dump(mode="json"), "needs_confirm": True}

    async def _run_options(mandate_id: str | None) -> dict[str, Any]:
        mandate = (
            await store.get_mandate(mandate_id)
            if mandate_id
            else await store.get_active_mandate()
        )
        if mandate is None:
            raise NotFoundError("No active mandate found; use /mandate and /confirm first")
        opts = await search_and_ask_preference(
            mandate=mandate,
            query=mandate.intent_text,
            catalog=resolved_catalog,
            llm=resolved_llm,
            limit=5,
        )
        container.last_options = opts
        return {
            "mandate_id": mandate.mandate_id,
            "options": [
                {
                    "index": idx + 1,
                    "product": o.product.model_dump(mode="json"),
                    "deterministic_score": o.deterministic_score,
                    "reason": o.reason,
                    "sanitized_description": o.sanitized_description,
                }
                for idx, o in enumerate(opts)
            ],
        }

    async def _pick_option(index: int, mandate_id: str | None) -> dict[str, Any]:
        if index < 1 or index > len(container.last_options):
            raise NotFoundError(f"Option #{index} not found; run /options first")
        selected = container.last_options[index - 1]
        mandate = (
            await store.get_mandate(mandate_id)
            if mandate_id
            else await store.get_active_mandate()
        )
        if mandate is None:
            raise NotFoundError("No active mandate found")
        prop = build_proposal_from_product(
            mandate=mandate, product=selected.product, rationale=selected.reason
        )
        case = await orchestrator.submit_proposal(prop, actor="shopping-agent")
        locked = await orchestrator.lock_cart(case.case_id, actor="user")
        return {"case": locked.model_dump(mode="json")}

    container.commands = CommandRegistry(
        orchestrator=orchestrator,
        compile_and_draft=_compile_and_draft,
        run_options=_run_options,
        pick_option=_pick_option,
    )
    return container


def get_container(request: Request) -> AppContainer:
    return request.app.state.container
