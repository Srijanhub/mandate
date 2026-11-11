from __future__ import annotations

import json

import httpx
import pytest
from mandate_core.domain.models import CaseSnapshot, Mandate, Money, Product, utcnow

from adapters.llm_astropods import AstropodsLLM
from adapters.notifier_console import ConsoleNotifier
from adapters.partner_elastic import ElasticSearchAdapter
from adapters.partner_kernel import KernelVerifier
from adapters.partner_render import RenderWorkflowsClient
from apps.api.config import Settings
from apps.api.dependencies import build_container
from apps.api.main import create_app


@pytest.mark.asyncio
async def test_partner_apis_fallback_and_bryntum_timelines() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        paypal_mode="mock",
        catalog_provider="mock",
        llm_provider="deterministic",
        recheck_poll_interval_seconds=3600,
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ready = await client.get("/ready")
            assert ready.status_code == 200
            ready_json = ready.json()
            assert "integrations_configured" in ready_json
            assert ready_json["integrations_configured"]["kernel"] is False

            status_res = await client.get("/integrations/status")
            assert status_res.status_code == 200
            names = {s["name"]: s for s in status_res.json()["services"]}
            assert names["paypal"]["mode"] == "mock"
            assert names["kernel"]["mode"] == "deterministic_fallback"
            assert names["elastic"]["mode"] == "deterministic_fallback"
            assert names["render_workflows"]["mode"] == "simulated"
            assert names["bryntum"]["configured"] is True

            # Seed a mandate & case via unified command flow for timeline + ledger search
            c1 = await client.post(
                "/commands",
                json={"text": "/mandate Buy birthday candle under $60, verified sellers only"},
            )
            assert c1.status_code == 200
            mandate_id = c1.json()["mandate"]["mandate_id"]
            assert (
                await client.post("/commands", json={"text": "/confirm", "mandate_id": mandate_id})
            ).status_code == 200
            assert (
                await client.post("/commands", json={"text": "/options", "mandate_id": mandate_id})
            ).status_code == 200
            assert (
                await client.post("/commands", json={"text": "/pick 1", "mandate_id": mandate_id})
            ).status_code == 200

            # Bryntum Calendar / Scheduler feeds
            m_sched = await client.get("/mandates/schedule")
            assert m_sched.status_code == 200
            assert m_sched.json()["format"] == "bryntum-scheduler-v1"
            assert len(m_sched.json()["events"]) >= 1

            c_timeline = await client.get("/cases/timeline")
            assert c_timeline.status_code == 200
            assert len(c_timeline.json()["events"]) >= 1

            # Elastic sync + semantic catalog & ledger search (deterministic fallback)
            sync_res = await client.post("/integrations/elastic/sync")
            assert sync_res.status_code == 200
            assert sync_res.json()["catalog_indexed"] >= 1
            assert sync_res.json()["ledger_indexed"] >= 1

            cat_search = await client.get("/catalog/semantic-search", params={"query": "candle"})
            assert cat_search.status_code == 200
            assert cat_search.json()["total"] >= 1

            led_search = await client.get("/ledger/search", params={"query": "MANDATE"})
            assert led_search.status_code == 200
            assert led_search.json()["total"] >= 1

            # Kernel URL verification fallback + SSRF block
            cat_items = (await client.get("/catalog/search", params={"limit": 1})).json()["products"]
            pid = cat_items[0]["product_id"]
            verify_res = await client.post("/catalog/verify-url", json={"product_id": pid})
            assert verify_res.status_code == 200
            assert verify_res.json()["verified"] is True
            assert verify_res.json()["mode"] == "deterministic_fallback"

            ssrf_res = await client.post(
                "/catalog/verify-url",
                json={"url": "http://127.0.0.1:8000/health"},
            )
            assert ssrf_res.status_code == 400

            # Render Workflow simulated trigger + poll
            trig = await client.post("/integrations/render/workflows/trigger", json={})
            assert trig.status_code == 200
            run_id = trig.json()["run_id"]
            assert trig.json()["mode"] == "simulated"
            assert trig.json()["status"] == "SUCCEEDED"

            poll = await client.get(f"/integrations/render/workflows/runs/{run_id}")
            assert poll.status_code == 200
            assert poll.json()["run_id"] == run_id

            # Zapier / Notifier test endpoint
            zap = await client.post(
                "/integrations/zapier/test",
                json={"message": "Testing notifier"},
            )
            assert zap.status_code == 200
            assert zap.json()["delivered"] is True


@pytest.mark.asyncio
async def test_partner_apis_live_transports_and_astropods_llm() -> None:
    def kernel_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/browsers":
            return httpx.Response(200, json={"browsers": []})
        if request.method == "POST" and request.url.path == "/browsers":
            return httpx.Response(
                201,
                json={"session_id": "kern-sess-1", "cdp_ws_url": "wss://kernel.test/cdp"},
            )
        if request.method == "DELETE" and request.url.path == "/browsers/kern-sess-1":
            return httpx.Response(204)
        if request.url.host == "merchant.example.com":
            return httpx.Response(200, text="<html><title>Verified Candle Shop</title></html>")
        return httpx.Response(404)

    def elastic_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_cluster/health":
            return httpx.Response(200, json={"status": "green"})
        if request.url.path.endswith("/_bulk"):
            return httpx.Response(200, json={"errors": False, "items": []})
        if request.url.path.endswith("/_search"):
            return httpx.Response(
                200,
                json={
                    "hits": {
                        "hits": [
                            {
                                "_id": "prod_1",
                                "_score": 4.2,
                                "_source": {"product_id": "prod_1", "title": "Artisan Candle"},
                            }
                        ]
                    }
                },
            )
        return httpx.Response(404)

    def render_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/v1/workflows":
            return httpx.Response(200, json=[])
        if request.method == "POST" and request.url.path == "/v1/tasks/mandate/sweep/runs":
            return httpx.Response(201, json={"id": "rnd-live-42", "status": "RUNNING"})
        if request.method == "GET" and request.url.path == "/v1/task-runs/rnd-live-42":
            return httpx.Response(200, json={"id": "rnd-live-42", "status": "SUCCEEDED"})
        return httpx.Response(404)

    def astro_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "gemini-3.8-flash"}]})
        body = json.loads(request.content.decode("utf-8"))
        system_msg = body["messages"][0]["content"]
        if "max_total_amount" in system_msg:
            content = json.dumps({"max_total_amount": "50.00", "currency": "USD"})
        elif "picks" in system_msg:
            content = json.dumps({"picks": [{"product_id": "p1", "reason": "Best match"}]})
        elif "verdict" in system_msg:
            content = json.dumps({"verdict": "ok", "reasons": []})
        else:
            content = "done"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content, "tool_calls": []}}]},
        )

    astro_llm = AstropodsLLM(
        gateway_url="https://astro.example.com",
        api_key="astro-test-key",
        transport=httpx.MockTransport(astro_handler),
    )
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        paypal_mode="mock",
        catalog_provider="mock",
        llm_provider="astropods",
        astro_gateway_url="https://astro.example.com",
        astro_gateway_api_key="astro-test-key",
        kernel_api_key="kern-test-key",
        elastic_url="https://elastic.example.com",
        elastic_api_key="es-test-key",
        render_api_key="rnd-test-key",
        render_workflow_task_slug="mandate/sweep",
        recheck_poll_interval_seconds=3600,
    )
    container = build_container(
        settings,
        llm=astro_llm,
        notifier=ConsoleNotifier(),
        kernel=KernelVerifier(
            api_key="kern-test-key",
            transport=httpx.MockTransport(kernel_handler),
        ),
        elastic=ElasticSearchAdapter(
            url="https://elastic.example.com",
            api_key="es-test-key",
            transport=httpx.MockTransport(elastic_handler),
        ),
        render_workflows=RenderWorkflowsClient(
            api_key="rnd-test-key",
            default_task_slug="mandate/sweep",
            transport=httpx.MockTransport(render_handler),
        ),
    )
    app = create_app(settings, container_override=container)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            probe = await client.get("/integrations/status", params={"probe": True})
            assert probe.status_code == 200
            services = {s["name"]: s for s in probe.json()["services"]}
            assert services["kernel"]["live_ok"] is True
            assert services["elastic"]["live_ok"] is True
            assert services["render_workflows"]["live_ok"] is True
            assert services["astropods"]["live_ok"] is True

            k_res = await client.post(
                "/catalog/verify-url",
                json={"url": "https://merchant.example.com/item/1"},
            )
            assert k_res.status_code == 200
            assert k_res.json()["mode"] == "live"
            assert k_res.json()["cdp_ready"] is True
            assert k_res.json()["observed_title"] == "Verified Candle Shop"

            e_res = await client.get("/catalog/semantic-search", params={"query": "candle"})
            assert e_res.status_code == 200
            assert e_res.json()["mode"] == "live"
            assert e_res.json()["hits"][0]["id"] == "prod_1"

            r_trig = await client.post(
                "/integrations/render/workflows/trigger",
                json={"run_local_recheck": False},
            )
            assert r_trig.status_code == 200
            assert r_trig.json()["run_id"] == "rnd-live-42"

            r_get = await client.get("/integrations/render/workflows/runs/rnd-live-42")
            assert r_get.status_code == 200
            assert r_get.json()["status"] == "SUCCEEDED"

    # Exercise AstropodsLLM port methods directly
    compiled = await astro_llm.compile_mandate("Spend under $50")
    assert compiled["max_total_amount"] == "50.00"

    prod = Product(
        product_id="p1",
        title="Candle",
        price=Money.of("15.00", "USD"),
        seller_id="s1",
        seller_name="Seller",
        seller_verified=True,
        payee_id="PAYEE-1",
    )
    picks = await astro_llm.rank_candidates(intent_text="candle", candidates=[prod])
    assert picks[0]["product_id"] == "p1"

    now = utcnow()
    mandate = Mandate(intent_text="candle", max_total=Money.of("50.00", "USD"), expires_at=now)
    snap = CaseSnapshot(
        case_id="case_1",
        checkpoint="C1",
        mandate_id=mandate.mandate_id,
        mandate_version=1,
        product_id="p1",
        title="Candle",
        quantity=1,
        unit_price=Money.of("15.00", "USD"),
        total_amount=Money.of("15.00", "USD"),
        seller_id="s1",
        seller_name="Seller",
        seller_verified=True,
        payee_id="PAYEE-1",
        in_stock=True,
        category="gifts",
    )
    verdict = await astro_llm.audit_snapshot(
        mandate=mandate, snapshot=snap, untrusted_product_text="Nice soy candle"
    )
    assert verdict.verdict == "ok"
