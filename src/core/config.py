from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "PVC Backend"
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_prefix: str = "/api"

    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    db_host: str = Field(default="127.0.0.1", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="pvc", alias="DB_NAME")
    db_user: str = Field(default="pvc", alias="DB_USER")
    db_password: str = Field(default="", alias="DB_PASSWORD")

    x_admin_key: str = Field(alias="X_ADMIN_KEY")
    cookie_name: str = Field(default="pvc_admin_session", alias="COOKIE_NAME")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    cookie_max_age_seconds: int = Field(default=28800, alias="COOKIE_MAX_AGE_SECONDS")
    cookie_samesite: str = Field(default="lax", alias="COOKIE_SAMESITE")
    cors_origins_raw: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")

    gcp_project_id: str | None = Field(default=None, alias="GCP_PROJECT_ID")
    gcp_region: str = Field(default="us-central1", alias="GCP_REGION")
    gcs_sample_bucket: str = Field(default="", alias="GCS_SAMPLE_BUCKET")
    gcs_output_bucket: str = Field(default="", alias="GCS_OUTPUT_BUCKET")

    llm_api_url: str | None = Field(default=None, alias="LLM_API_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")

    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    github_owner: str | None = Field(default=None, alias="GITHUB_OWNER")
    github_repo: str | None = Field(default=None, alias="GITHUB_REPO")
    github_ref: str = Field(default="main", alias="GITHUB_REF")
    github_api_url: str = Field(default="https://api.github.com", alias="GITHUB_API_URL")
    github_start_workflow: str | None = Field(default=None, alias="GITHUB_START_WORKFLOW")
    github_start_workflow_inputs_json: str = Field(
        default="{}",
        alias="GITHUB_START_WORKFLOW_INPUTS_JSON",
    )

    tts_endpoint: str | None = Field(default=None, alias="TTS_ENDPOINT")
    tts_health_path: str = Field(default="/health", alias="TTS_HEALTH_PATH")
    tts_ws_path: str = Field(default="/ws/generate", alias="TTS_WS_PATH")
    tts_boot_timeout_seconds: int = Field(default=600, alias="TTS_BOOT_TIMEOUT_SECONDS")

    backend_public_url: str | None = Field(default=None, alias="BACKEND_PUBLIC_URL")
    internal_secret: str | None = Field(default=None, alias="INTERNAL_SECRET")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins_raw.split(",") if value.strip()]

    @property
    def github_start_workflow_inputs(self) -> dict[str, str]:
        parsed = json.loads(self.github_start_workflow_inputs_json or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("GITHUB_START_WORKFLOW_INPUTS_JSON must be a JSON object")
        return {str(key): str(value) for key, value in parsed.items()}


@lru_cache
def load_settings() -> Settings:
    return Settings()
