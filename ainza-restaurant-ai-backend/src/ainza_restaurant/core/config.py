from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ainza-restaurant-ai-backend"
    app_env: str = "local"
    debug: bool = False
    database_url: str = "postgresql+asyncpg://ainza:ainza_local_password@localhost:5432/ainza"
    frontend_origins: list[str] = Field(default_factory=list)
    availability_proposal_ttl_minutes: int = Field(default=15, gt=0, le=60)

    # ── Primary / legacy provider (llama.cpp or any OpenAI-compat endpoint) ─────
    local_llm_base_url: str = "http://127.0.0.1:8081/v1"
    local_llm_model: str = "ainza-qwen3-8b"
    local_llm_runtime_mode: Literal["local", "remote"] = "local"
    local_llm_api_key: SecretStr | None = None
    local_llm_connect_timeout_seconds: int = Field(default=10, gt=0, le=60)
    local_llm_timeout_seconds: int = Field(default=240, gt=0, le=600)
    local_llm_max_tokens: int = Field(default=512, gt=1, le=2048)
    local_llm_max_tool_rounds: int = Field(default=6, gt=0, le=12)
    local_llm_context_turns: int = Field(default=12, gt=0, le=30)

    # ── Cloudflare Workers AI fallback ──────────────────────────────────────────
    # Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN to enable.
    # Endpoint: https://api.cloudflare.com/client/v4/accounts/{id}/ai/v1
    cloudflare_account_id: str | None = None
    cloudflare_api_token: SecretStr | None = None
    cloudflare_model: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    cloudflare_timeout_seconds: int = Field(default=60, gt=0, le=300)
    cloudflare_max_tokens: int = Field(default=512, gt=1, le=2048)

    # ── Provider selection ───────────────────────────────────────────────────────
    # "auto"       → use local_llm_base_url as primary (existing behaviour);
    #                if cloudflare credentials exist, add CF as fallback.
    # "cloudflare" → use Cloudflare as primary; local_llm as secondary fallback.
    ai_primary_provider: Literal["auto", "cloudflare"] = "auto"

    ai_confirmation_ttl_minutes: int = Field(default=15, gt=0, le=60)

    # ── Speech-to-text (whisper.cpp — unchanged) ─────────────────────────────────
    local_stt_base_url: str = "http://127.0.0.1:8082"
    local_stt_timeout_seconds: int = Field(default=180, gt=0, le=300)
    local_stt_max_audio_bytes: int = Field(default=8_388_608, gt=0, le=16_777_216)
    local_stt_max_audio_seconds: int = Field(default=30, gt=0, le=60)
    local_stt_max_concurrent_requests: int = Field(default=1, ge=1, le=1)
    local_stt_language: str = "auto"

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug(cls, value: Any) -> Any:
        if isinstance(value, str) and value.casefold() in {"release", "prod", "production"}:
            return False
        return value

    @field_validator("local_llm_api_key", mode="before")
    @classmethod
    def normalize_local_llm_api_key(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("cloudflare_api_token", "cloudflare_account_id", mode="before")
    @classmethod
    def normalize_cloudflare_secret(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def cloudflare_enabled(self) -> bool:
        return bool(self.cloudflare_account_id and self.cloudflare_api_token)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
