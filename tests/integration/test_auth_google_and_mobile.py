from __future__ import annotations

import time
from typing import Any

import httpx
import pytest

from adapters.auth import (
    GoogleIdentityVerifier,
    SmsOtpSender,
    issue_session_token,
    verify_session_token,
)
from apps.api.config import Settings
from apps.api.dependencies import build_container
from apps.api.main import create_app


@pytest.mark.asyncio
async def test_google_auth_demo_mobile_otp_linking_and_mandate_attribution() -> None:
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        paypal_mode="mock",
        catalog_provider="mock",
        llm_provider="deterministic",
        require_auth=True,
        api_user_token="user-static-secret",
        api_admin_token="admin-static-secret",
        auth_jwt_secret="unit-test-jwt-secret-key",
        auth_allow_demo_mode=True,
        auth_expose_demo_otp=True,
        recheck_poll_interval_seconds=3600,
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. Public auth config exposes demo Google + phone OTP availability
            cfg = await client.get("/auth/config")
            assert cfg.status_code == 200
            cfg_json = cfg.json()
            assert cfg_json["google_enabled"] is True
            assert cfg_json["google_mode"] == "demo"
            assert cfg_json["phone_mode"] == "demo"
            assert cfg_json["demo_otp_exposed"] is True
            assert cfg_json["require_auth"] is True

            # Unauthenticated /auth/me must return 401
            assert (await client.get("/auth/me")).status_code == 401

            # 2. Sign in with Google (demo mode)
            g_res = await client.post(
                "/auth/google",
                json={"demo_email": "Vinay@Example.com", "demo_name": "Vinay Khandia"},
            )
            assert g_res.status_code == 200
            g_data = g_res.json()
            assert g_data["mode"] == "demo"
            jwt_token = g_data["access_token"]
            user_id = g_data["user"]["user_id"]
            assert user_id.startswith("usr_")
            assert g_data["user"]["email"] == "vinay@example.com"
            assert g_data["user"]["auth_providers"] == ["google"]

            # 3. Verify /auth/me resolves live user profile
            me_res = await client.get("/auth/me", headers={"Authorization": f"Bearer {jwt_token}"})
            assert me_res.status_code == 200
            assert me_res.json()["user_id"] == user_id

            # 4. Link mobile number via OTP while signed in with Google
            bad_phone = await client.post("/auth/phone/request-otp", json={"phone_number": "98765"})
            assert bad_phone.status_code == 400

            otp_req = await client.post(
                "/auth/phone/request-otp", json={"phone_number": "+1 (415) 555-0199"}
            )
            assert otp_req.status_code == 200
            otp_payload = otp_req.json()
            assert otp_payload["phone_number"] == "+14155550199"
            assert otp_payload["mode"] == "demo"
            challenge_id = otp_payload["challenge_id"]
            demo_otp = otp_payload["demo_otp"]
            assert isinstance(demo_otp, str) and len(demo_otp) == 6

            # Wrong OTP fails and does not consume immediately
            wrong_verify = await client.post(
                "/auth/phone/verify-otp",
                json={
                    "challenge_id": challenge_id,
                    "phone_number": "+14155550199",
                    "code": "000000" if demo_otp != "000000" else "999999",
                },
            )
            assert wrong_verify.status_code == 400

            # Correct OTP with Google Bearer token links phone to the SAME user_id
            ok_verify = await client.post(
                "/auth/phone/verify-otp",
                headers={"Authorization": f"Bearer {jwt_token}"},
                json={
                    "challenge_id": challenge_id,
                    "phone_number": "+14155550199",
                    "code": demo_otp,
                },
            )
            assert ok_verify.status_code == 200
            linked_user = ok_verify.json()["user"]
            assert linked_user["user_id"] == user_id
            assert linked_user["phone_number"] == "+14155550199"
            assert set(linked_user["auth_providers"]) == {"google", "phone"}

            # Replay of already-consumed OTP must fail
            replay = await client.post(
                "/auth/phone/verify-otp",
                json={
                    "challenge_id": challenge_id,
                    "phone_number": "+14155550199",
                    "code": demo_otp,
                },
            )
            assert replay.status_code == 400

            # 5. Authenticated JWT works on protected routes and sets Mandate owner_id/actor
            comp = await client.post(
                "/mandates/compile",
                headers={"Authorization": f"Bearer {jwt_token}"},
                json={"prompt": "Buy candle under $50, verified sellers only"},
            )
            assert comp.status_code == 201
            assert comp.json()["mandate"]["owner_id"] == user_id

            # User JWT cannot call admin-only /demo-lab/reset (403)
            admin_attempt = await client.post(
                "/demo-lab/reset",
                headers={"Authorization": f"Bearer {jwt_token}"},
            )
            assert admin_attempt.status_code == 403

            # Static API tokens continue to work alongside JWTs
            static_ok = await client.post(
                "/demo-lab/reset",
                headers={"Authorization": "Bearer admin-static-secret"},
            )
            assert static_ok.status_code == 200

            # Tampered JWT is rejected with 401
            tampered_jwt = jwt_token[:-4] + "abcd"
            assert (
                await client.get("/auth/me", headers={"Authorization": f"Bearer {tampered_jwt}"})
            ).status_code == 401


@pytest.mark.asyncio
async def test_live_google_verifier_and_twilio_sms_mode_and_otp_lockouts() -> None:
    twilio_requests: list[dict[str, Any]] = []

    def twilio_handler(request: httpx.Request) -> httpx.Response:
        twilio_requests.append({"url": str(request.url), "body": request.content.decode("utf-8")})
        return httpx.Response(201, json={"sid": "SM_TEST_123", "status": "queued"})

    def fake_google_verify(raw_token: str, audience: str) -> dict[str, Any]:
        assert audience == "test-client.apps.googleusercontent.com"
        if raw_token == "valid-google-jwt":
            return {
                "sub": "google-sub-999",
                "email": "judge@paypal-hackathon.org",
                "email_verified": True,
                "name": "Hackathon Judge",
                "picture": "https://example.com/avatar.png",
            }
        if raw_token == "unverified-email-jwt":
            return {
                "sub": "google-sub-unv",
                "email": "unverified@example.com",
                "email_verified": False,
            }
        raise ValueError("Invalid token signature")

    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        paypal_mode="mock",
        catalog_provider="mock",
        llm_provider="deterministic",
        google_client_id="test-client.apps.googleusercontent.com",
        twilio_account_sid="AC_TEST_SID",
        twilio_auth_token="twilio-secret-token",
        twilio_from_number="+14155550000",
        auth_jwt_secret="live-mode-test-secret",
        auth_allow_demo_mode=False,
        auth_expose_demo_otp=False,
        recheck_poll_interval_seconds=3600,
    )
    container = build_container(
        settings,
        google_verifier=GoogleIdentityVerifier(
            client_id=settings.google_client_id,
            allow_demo_mode=False,
            verify_fn=fake_google_verify,
        ),
        sms_sender=SmsOtpSender(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_from_number,
            transport=httpx.MockTransport(twilio_handler),
        ),
    )
    app = create_app(settings, container_override=container)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            cfg = (await client.get("/auth/config")).json()
            assert cfg["google_mode"] == "live"
            assert cfg["phone_mode"] == "twilio"
            assert cfg["demo_otp_exposed"] is False

            # Live Google mode rejects demo_email bypass and unverified/bad tokens
            assert (await client.post("/auth/google", json={"demo_email": "x@y.com"})).status_code == 400
            assert (
                await client.post("/auth/google", json={"id_token": "unverified-email-jwt"})
            ).status_code == 400
            assert (await client.post("/auth/google", json={"id_token": "bad"})).status_code == 400

            ok_g = await client.post("/auth/google", json={"id_token": "valid-google-jwt"})
            assert ok_g.status_code == 200
            assert ok_g.json()["mode"] == "live"
            assert ok_g.json()["user"]["avatar_url"] == "https://example.com/avatar.png"

            # Twilio SMS sends OTP without exposing demo_otp in HTTP response
            r_otp = await client.post("/auth/phone/request-otp", json={"phone_number": "+919876543210"})
            assert r_otp.status_code == 200
            r_json = r_otp.json()
            assert r_json["mode"] == "twilio"
            assert r_json["demo_otp"] is None
            assert len(twilio_requests) == 1

            # 5 wrong attempts trigger OTP lockout
            cid = r_json["challenge_id"]
            for _ in range(5):
                bad = await client.post(
                    "/auth/phone/verify-otp",
                    json={"challenge_id": cid, "phone_number": "+919876543210", "code": "000000"},
                )
                assert bad.status_code == 400
            locked = await client.post(
                "/auth/phone/verify-otp",
                json={"challenge_id": cid, "phone_number": "+919876543210", "code": "000000"},
            )
            assert locked.status_code == 400
            assert "used or superseded" in locked.json()["error"]["message"]

            # Per-phone OTP spam protection (5 requests per 5-minute window -> 6th blocked)
            for _ in range(4):
                assert (
                    await client.post("/auth/phone/request-otp", json={"phone_number": "+919876543210"})
                ).status_code == 200
            rate_limited = await client.post(
                "/auth/phone/request-otp", json={"phone_number": "+919876543210"}
            )
            assert rate_limited.status_code == 400
            assert "Too many OTP requests" in rate_limited.json()["error"]["message"]


def test_jwt_issue_verify_and_expiration() -> None:
    tok, ttl = issue_session_token(
        user_id="usr_123",
        role="user",
        email="u@example.com",
        phone_number=None,
        display_name="User One",
        auth_method="google",
        secret="secret-key-abc",
        ttl_seconds=120,
    )
    assert ttl == 120
    claims = verify_session_token(tok, secret="secret-key-abc")
    assert claims.user_id == "usr_123"
    assert claims.email == "u@example.com"
    assert claims.exp > int(time.time())

    with pytest.raises(ValueError):
        verify_session_token(tok, secret="wrong-secret")
