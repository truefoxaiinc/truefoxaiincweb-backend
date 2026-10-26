import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    database_path: Path = Path("./data/rag.sqlite3")
    admin_api_key: str = ""
    admin_username: str = "admin@gmail.com"
    admin_password: str = ""
    admin_session_secret: str = ""
    admin_token_minutes: int = 480
    admin_jwt_issuer: str = "truefox-ai-api"
    admin_jwt_audience: str = "truefox-ai-admin"
    admin_cookie_domain: str = ".truefoxaiinc.com"
    leads_webhook_url: str = ""
    lead_smtp_host: str = ""
    lead_smtp_port: int = Field(default=587, ge=1, le=65535)
    lead_smtp_username: str = ""
    lead_smtp_password: str = ""
    lead_email_from: str = ""
    lead_email_to: str = ""
    lead_smtp_ssl: bool = False
    company_site_url: str = "https://truefoxaiinc.com"
    frontend_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    trusted_proxy_ips: Annotated[list[str], NoDecode] = Field(default_factory=list)
    conversation_capability_ttl_hours: int = Field(default=24, ge=1, le=720)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    chat_model: str = "openai/gpt-4o"
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = 512
    rag_top_k: int = 3
    rag_min_score: float = 0.32
    max_context_chars: int = 6_000
    chat_rate_limit_per_minute: int = 20
    mock_llm: bool = False
    log_user_messages: bool = False

    @field_validator("frontend_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("trusted_proxy_ips", mode="before")
    @classmethod
    def parse_trusted_proxy_ips(cls, value: object) -> object:
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        if not isinstance(value, list):
            return value
        return [str(ipaddress.ip_network(item, strict=False)) for item in value]

    @field_validator("openrouter_base_url", mode="before")
    @classmethod
    def empty_openrouter_base_url_is_default(cls, value: object) -> object:
        return "https://openrouter.ai/api/v1" if value == "" else value

    @property
    def database_file(self) -> Path:
        return self.database_path.expanduser().resolve()

    @property
    def llm_ready(self) -> bool:
        return bool(self.openrouter_api_key) or self.mock_llm

    @property
    def session_secret(self) -> str:
        return self.admin_session_secret or self.admin_password

    @property
    def allowed_frontend_origins(self) -> list[str]:
        origins = {origin.rstrip("/") for origin in self.frontend_origins}
        site = self.company_site_url.rstrip("/")
        origins.add(site)
        parsed = urlparse(site)
        if parsed.scheme and parsed.hostname:
            hostname = parsed.hostname.removeprefix("www.")
            origins.add(f"{parsed.scheme}://{hostname}")
            origins.add(f"{parsed.scheme}://www.{hostname}")
        if self.app_env != "production":
            origins.update({"http://localhost:3000", "http://127.0.0.1:3000"})
        return sorted(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()
