from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    database_url: str = "sqlite+aiosqlite:///./data/mandate.db"

    api_admin_token: str = "dev-admin-token-change-me"
    api_user_token: str = "dev-user-token-change-me"
    require_auth: bool = False

    google_client_id: str = ""
    auth_jwt_secret: str = "dev-mandate-jwt-secret-change-me"
    auth_token_ttl_seconds: int = 86_400
    auth_allow_demo_mode: bool = True
    auth_expose_demo_otp: bool = True

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    paypal_mode: str = "mock"  # mock | sandbox | live
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_sandbox_seller_a_id: str = "SELLER-A-VERIFIED"
    paypal_sandbox_seller_b_id: str = "SELLER-B-ATTACKER"

    llm_provider: str = "gemini"  # gemini | groq | astropods | deterministic
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"

    astro_gateway_url: str = ""
    astro_gateway_api_key: str = ""
    astro_model: str = "gemini-3.6-flash"

    catalog_provider: str = "mock"  # mock | channel3
    channel3_api_key: str = ""

    kernel_api_key: str = ""
    kernel_base_url: str = "https://api.onkernel.com"

    elastic_url: str = ""
    elastic_api_key: str = ""
    elastic_index_prefix: str = "mandate"

    render_api_key: str = ""
    render_api_base: str = "https://api.render.com/v1"
    render_workflow_task_slug: str = ""

    notifier_provider: str = "console"  # console | webhook
    zapier_webhook_url: str = ""

    recheck_poll_interval_seconds: int = 30
    enable_demo_lab: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def effective_allow_demo_mode(self) -> bool:
        return False if self.is_production else self.auth_allow_demo_mode

    @property
    def effective_expose_demo_otp(self) -> bool:
        return False if self.is_production else self.auth_expose_demo_otp

    def validate_security_posture(self) -> None:
        """Fail closed in production if auth is enabled with insecure default secrets."""
        if not (self.is_production and self.require_auth):
            return
        if (
            not self.auth_jwt_secret.strip()
            or self.auth_jwt_secret == "dev-mandate-jwt-secret-change-me"
            or len(self.auth_jwt_secret.strip()) < 16
        ):
            raise ValueError(
                "Production REQUIRE_AUTH=true requires a strong non-default AUTH_JWT_SECRET (>= 16 chars)"
            )
        if not self.api_admin_token.strip() or self.api_admin_token == "dev-admin-token-change-me":
            raise ValueError(
                "Production REQUIRE_AUTH=true requires a non-default API_ADMIN_TOKEN"
            )
        if not self.api_user_token.strip() or self.api_user_token == "dev-user-token-change-me":
            raise ValueError(
                "Production REQUIRE_AUTH=true requires a non-default API_USER_TOKEN"
            )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
