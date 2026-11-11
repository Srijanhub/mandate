import httpx
import pytest

from apps.api.config import Settings
from apps.api.main import create_app


@pytest.mark.asyncio
async def test_api_unified_commands_r1_to_r9_email_pack_and_ledger_ag_grid() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        paypal_mode="mock",
        catalog_provider="mock",
        llm_provider="deterministic",
        enable_demo_lab=True,
        recheck_poll_interval_seconds=3600,
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/ready")).status_code == 200

            # Control plane vs data plane: untrusted source cannot run /approve
            bad_cmd = await client.post(
                "/commands",
                json={"text": "/approve", "source": "product_text"},
            )
            assert bad_cmd.status_code == 400
            assert bad_cmd.json()["error"]["code"] == "UNTRUSTED_CONTROL_PLANE_SOURCE"

            # Unified command flow: /mandate -> /confirm -> /options -> /pick 1 -> /approve -> /why
            c1 = await client.post(
                "/commands",
                json={"text": "/mandate Buy birthday candle under $60, verified sellers only"},
            )
            assert c1.status_code == 200
            mandate_id = c1.json()["mandate"]["mandate_id"]
            assert c1.json()["mandate"]["status"] == "DRAFT"

            c2 = await client.post(
                "/commands",
                json={"text": "/confirm", "mandate_id": mandate_id},
            )
            assert c2.status_code == 200
            assert c2.json()["mandate"]["status"] == "ACTIVE"

            c3 = await client.post(
                "/commands",
                json={"text": "/options", "mandate_id": mandate_id},
            )
            assert c3.status_code == 200
            assert len(c3.json()["options"]) >= 1

            c4 = await client.post(
                "/commands",
                json={"text": "/pick 1", "mandate_id": mandate_id},
            )
            assert c4.status_code == 200
            case_id = c4.json()["case"]["case_id"]
            assert c4.json()["case"]["state"] == "AWAITING_APPROVAL"

            c5 = await client.post(
                "/commands",
                json={"text": f"/approve {case_id}"},
            )
            assert c5.status_code == 200
            assert c5.json()["case"]["state"] == "VERIFIED"

            why = await client.get(f"/cases/{case_id}/why")
            assert why.status_code == 200
            assert len(why.json()["passed_checks"]) >= 8

            # Webhook signature verification + dedup
            bad_wh = await client.post(
                "/webhooks/paypal",
                headers={
                    "paypal-transmission-id": "t1",
                    "paypal-transmission-time": "2026-11-11T00:00:00Z",
                    "paypal-transmission-sig": "INVALID",
                },
                json={"id": "WH-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"},
            )
            assert bad_wh.status_code == 401

            # Second domain policy pack: Email agent
            email_ok = await client.post(
                "/packs/email/check",
                json={"subject": "Hi", "recipients": ["bob@company.com"]},
            )
            assert email_ok.status_code == 200
            assert email_ok.json()["decision"]["allow"] is True

            email_bad = await client.post(
                "/packs/email/check",
                json={"subject": "Leak", "recipients": ["evil@outside.org"]},
            )
            assert email_bad.status_code == 200
            assert email_bad.json()["decision"]["allow"] is False

            # Run Demo Lab R1..R8, check AG Grid + trust score, then R9 tamper detection!
            for code in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"):
                res = await client.post(f"/demo-lab/run/{code}")
                assert res.status_code == 200, f"{code} failed: {res.text}"

            assert (await client.get("/ledger/verify")).json()["valid"] is True

            ag = await client.get("/ledger?startRow=0&endRow=5&sortDir=desc")
            assert ag.status_code == 200
            assert len(ag.json()["rows"]) == 5
            assert ag.json()["lastRow"] > 5

            trust = await client.get("/ledger/trust-score")
            assert trust.status_code == 200
            assert 0.0 <= trust.json()["trust_score_percent"] <= 100.0

            # R9: tamper a ledger row and verify chain catches it
            r9 = await client.post("/demo-lab/run/R9")
            assert r9.status_code == 200
            assert r9.json()["verify"]["valid"] is False
            assert r9.json()["verify"]["first_broken_seq"] == r9.json()["tampered_seq"]
