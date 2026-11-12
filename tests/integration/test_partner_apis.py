from __future__ import annotations

import json
from typing import Any

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
        _env_file=None,
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
            assert names["kernel"]["mode"] == "unconfigured_fallback"
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

            # Kernel URL verification fail-closed fallback + SSRF block
            cat_items = (await client.get("/catalog/search", params={"limit": 1})).json()["products"]
            pid = cat_items[0]["product_id"]
            verify_res = await client.post("/catalog/verify-url", json={"product_id": pid})
            assert verify_res.status_code == 200
            assert verify_res.json()["verified"] is False
            assert verify_res.json()["mode"] == "unconfigured_fallback"
            assert verify_res.json()["observed_price"] is None

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
        _env_file=None,
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

    # Elastic Cloud Serverless disables /_cluster/health (410) and probes root /
    def serverless_elastic_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_cluster/health":
            return httpx.Response(410, json={"status": 410})
        if request.url.path == "/":
            return httpx.Response(200, json={"name": "serverless"})
        return httpx.Response(404)

    serverless_elastic = ElasticSearchAdapter(
        url="https://serverless.es.example.cloud:443",
        api_key="es-serverless-key",
        transport=httpx.MockTransport(serverless_elastic_handler),
    )
    serverless_probe = await serverless_elastic.probe()
    assert serverless_probe["ok"] is True
    assert serverless_probe["status_code"] == 200


@pytest.mark.asyncio
async def test_security_hardening_lazy_elastic_render_channel3_and_concurrent_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import socket
    from datetime import timedelta
    from types import SimpleNamespace

    from mandate_core.domain.errors import ValidationError

    from adapters.catalog_channel3 import Channel3Catalog
    from adapters.errors import ExternalServiceError
    from adapters.partner_elastic import serialize_ledger_docs
    from adapters.partner_kernel import validate_public_url
    from scripts.export_postman import openapi_to_postman

    # 1. Kernel DNS SSRF blocking (IPv4 & IPv6) + redirect SSRF blocking + price parsing
    def _fake_getaddrinfo_private(host: str, port: Any, **kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0)),
        ]

    with monkeypatch.context() as mp:
        mp.setattr(socket, "getaddrinfo", _fake_getaddrinfo_private)
        with pytest.raises(ValidationError):
            validate_public_url("https://rebind.attacker.example/item")

    def redirect_kernel_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/browsers":
            return httpx.Response(201, json={"session_id": "s1", "cdp_ws_url": "wss://k.test/cdp"})
        if request.method == "DELETE" and request.url.path == "/browsers/s1":
            return httpx.Response(204)
        if request.url.host == "hop.example.com":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:8000/admin"})
        if request.url.host == "priced.example.com":
            return httpx.Response(
                200,
                text=(
                    '<html><head><title>Soy Candle</title>'
                    '<meta property="product:price:amount" content="38.50">'
                    '<meta property="product:price:currency" content="USD">'
                    "</head><body>ok</body></html>"
                ),
            )
        return httpx.Response(404)

    kern = KernelVerifier(
        api_key="kern-key",
        transport=httpx.MockTransport(redirect_kernel_handler),
    )
    with pytest.raises(ValidationError):
        await kern.verify_merchant_url("https://hop.example.com/go")

    priced = await kern.verify_merchant_url(
        "https://priced.example.com/item", expected_price="99.99 USD"
    )
    assert priced["verified"] is True
    assert "direct_http_metadata_fetch" in priced["checks"]
    assert priced["observed_price"] == "38.50 USD"  # Parsed from page, not expected_price

    # 2. Auth guard on /integrations/status?probe=true + concurrent timeout handling
    class _SlowKernel(KernelVerifier):
        async def probe(self) -> dict[str, Any]:
            await asyncio.sleep(4.0)
            return {"configured": True, "ok": True, "mode": "live"}

    auth_settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        paypal_mode="mock",
        catalog_provider="mock",
        llm_provider="deterministic",
        require_auth=True,
        api_user_token="user-secret",
        api_admin_token="admin-secret",
        recheck_poll_interval_seconds=3600,
    )
    slow_container = build_container(
        auth_settings,
        kernel=_SlowKernel(api_key="slow-kern"),
    )
    auth_app = create_app(auth_settings, container_override=slow_container)
    async with auth_app.router.lifespan_context(auth_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=auth_app), base_url="http://test"
        ) as client:
            r_public = await client.get("/integrations/status")
            assert r_public.status_code == 200
            r_unauth_probe = await client.get("/integrations/status", params={"probe": True})
            assert r_unauth_probe.status_code == 401
            r_authed_probe = await client.get(
                "/integrations/status",
                params={"probe": True},
                headers={"Authorization": "Bearer user-secret"},
            )
            assert r_authed_probe.status_code == 200
            probed_map = {s["name"]: s for s in r_authed_probe.json()["services"]}
            assert probed_map["kernel"]["live_ok"] is False

    # 3. Render slug/run_id traversal rejection + HTTP >= 400 -> ExternalServiceError (502)
    def failing_render_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/tasks/bad-task/runs":
            return httpx.Response(404, json={"message": "Not found"})
        return httpx.Response(500)

    rnd = RenderWorkflowsClient(
        api_key="rnd-key",
        transport=httpx.MockTransport(failing_render_handler),
    )
    with pytest.raises(ValidationError):
        await rnd.trigger_task(task_slug="../etc/passwd")
    with pytest.raises(ValidationError):
        await rnd.get_run("../../admin")
    with pytest.raises(ExternalServiceError):
        await rnd.trigger_task(task_slug="bad-task")

    # 4. Lazy Elastic fallback + JSON ledger payload + Astropods resilience + Channel3 empty query
    catalog_calls: list[str] = []

    class _CountingCatalog:
        async def search(self, query: str, **kwargs: Any) -> list[Product]:
            catalog_calls.append(query)
            return []

        async def get(self, product_id: str) -> Product | None:
            return None

    live_es = ElasticSearchAdapter(
        url="https://es.test",
        api_key="es-key",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"hits": {"hits": []}})
        ),
    )
    lazy_settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        paypal_mode="mock",
        llm_provider="deterministic",
        recheck_poll_interval_seconds=3600,
    )
    lazy_container = build_container(
        lazy_settings,
        catalog=_CountingCatalog(),
        elastic=live_es,
    )
    lazy_app = create_app(lazy_settings, container_override=lazy_container)
    async with lazy_app.router.lifespan_context(lazy_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=lazy_app), base_url="http://test"
        ) as client:
            r_cat = await client.get("/catalog/semantic-search", params={"query": "candle"})
            assert r_cat.status_code == 200
            assert catalog_calls == []

            # Bryntum schedule clamp endDate >= startDate even when deliver_by < created_at
            now = utcnow()
            past_mandate = Mandate(
                intent_text="past delivery test",
                max_total=Money.of("25.00", "USD"),
                deliver_by=now - timedelta(days=2),
                expires_at=now + timedelta(hours=1),
                created_at=now,
                updated_at=now,
            )
            await lazy_container.store.save_mandate(past_mandate)
            sched = (await client.get("/mandates/schedule")).json()
            assert sched["events"][0]["endDate"] >= sched["events"][0]["startDate"]

    led_docs = serialize_ledger_docs(
        [
            SimpleNamespace(
                seq=1,
                event_type="TEST",
                case_id="c1",
                mandate_id="m1",
                actor="user",
                payload={"nested": True, "amount": "10.00"},
                hash="h1",
                created_at=utcnow(),
            )
        ]
    )
    assert led_docs[0][1]["payload_json"] == '{"nested": true, "amount": "10.00"}'

    # Channel3 does not rewrite "" to "gift"
    seen_ch3_queries: list[str] = []

    class _FakeCh3Client:
        class products:
            @staticmethod
            def search(**kwargs: Any) -> list[Any]:
                seen_ch3_queries.append(str(kwargs.get("query")))
                if kwargs.get("query") == "":
                    raise ValueError("empty query rejected")
                return []

    ch3 = Channel3Catalog(client=_FakeCh3Client())
    assert await ch3.search("") == []
    assert seen_ch3_queries == [""]

    # Astropods malformed choices, fenced JSON, and dict tool arguments
    bad_astro = AstropodsLLM(
        gateway_url="https://astro.test",
        api_key="k",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": []})),
    )
    assert await bad_astro.rank_candidates(intent_text="x", candidates=[]) == []
    snap = CaseSnapshot(
        case_id="c2",
        checkpoint="C3",
        mandate_id="m2",
        mandate_version=1,
        product_id="p1",
        title="Item",
        quantity=1,
        unit_price=Money.of("10.00", "USD"),
        total_amount=Money.of("10.00", "USD"),
        seller_id="s1",
        seller_name="Seller",
        seller_verified=True,
        payee_id="P1",
        in_stock=True,
        category="gifts",
    )
    m_obj = Mandate(intent_text="x", max_total=Money.of("20.00", "USD"), expires_at=utcnow())
    assert (await bad_astro.audit_snapshot(mandate=m_obj, snapshot=snap, untrusted_product_text="ok")).verdict == "flag"

    # Astropods dict + malformed tool_call arguments
    astro_turns = {"n": 0}
    seen_tool_results: list[str] = []

    def astro_tool_handler(request: httpx.Request) -> httpx.Response:
        astro_turns["n"] += 1
        body = json.loads(request.content.decode("utf-8"))
        for m in body.get("messages", []):
            if m.get("role") == "tool":
                seen_tool_results.append(str(m.get("content", "")))
        if astro_turns["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "tc-dict",
                                        "type": "function",
                                        "function": {
                                            "name": "search_products",
                                            "arguments": {"query": "candle", "limit": 2},
                                        },
                                    },
                                    {
                                        "id": "tc-badjson",
                                        "type": "function",
                                        "function": {
                                            "name": "propose_purchase",
                                            "arguments": "{invalid json",
                                        },
                                    },
                                ],
                            }
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": "Finished"}}]})

    astro_tools = AstropodsLLM(
        gateway_url="https://astro.test",
        api_key="k",
        transport=httpx.MockTransport(astro_tool_handler),
    )

    async def _mock_search(q: str, lim: int) -> list[dict[str, Any]]:
        return [{"product_id": "p1", "title": q}]

    async def _mock_propose(pid: str, qty: int, rat: str) -> dict[str, Any]:
        return {"case_id": "c1"}

    tool_out = await astro_tools.run_shopping_tools(
        query="candle", mandate=m_obj, search_fn=_mock_search, propose_fn=_mock_propose
    )
    assert tool_out["output_text"] == "Finished"
    assert any("Invalid JSON tool arguments" in r for r in seen_tool_results)

    # Postman export includes collection auth + non-empty schema examples
    collection = openapi_to_postman(lazy_app.openapi())
    assert collection["auth"]["type"] == "bearer"
    post_items = [it for it in collection["item"] if it["request"]["method"] == "POST" and "body" in it["request"]]
    assert post_items
    assert any(it["request"]["body"]["raw"] != "{}" for it in post_items)
