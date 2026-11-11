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

    paypal_mode: str = "mock"  # mock | sandbox | live
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_sandbox_seller_a_id: str = "SELLER-A-VERIFIED"
    paypal_sandbox_seller_b_id: str = "SELLER-B-ATTACKER"

    llm_provider: str = "gemini"  # gemini | groq | deterministic
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    catalog_provider: str = "mock"  # mock | channel3
    channel3_api_key: str = ""

    notifier_provider: str = "console"  # console | webhook
    zapier_webhook_url: str = ""

    recheck_poll_interval_seconds: int = 30
    enable_demo_lab: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
