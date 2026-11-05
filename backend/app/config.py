"""12-factor configuration: everything comes from environment variables (or a local .env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM ---
    gemini_api_key: str | None = Field(default=None, repr=False)
    # Chosen with evals/answer_eval.py: same quality as 3.8-flash on our set, lower latency.
    llm_model: str = "gemini-3.5-flash"
    # Tried in order when the primary model is overloaded / rate-limited (429, 5xx).
    llm_fallback_models: list[str] = ["gemini-3.1-flash-lite", "gemini-3.8-flash"]
    llm_temperature: float = 0.2
    llm_timeout_s: float = 60.0
    # USD per 1M tokens, used only for the cost estimate shown in traces. Set these to the
    # current price of whichever model you run; the defaults are only a rough flash-class estimate.
    llm_price_input_per_m: float = 0.30
    llm_price_output_per_m: float = 2.50

    # --- Retrieval ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str | None = None
    retrieval_top_k: int = 6
    retrieval_min_dense_score: float = 0.35

    # --- Agent / guardrails ---
    agent_max_steps: int = 4
    followup_suggestions: bool = True
    max_question_chars: int = 2000
    max_history_messages: int = 8
    max_upload_bytes: int = 2_000_000
    max_audio_bytes: int = 20_000_000

    # --- Storage / server ---
    database_path: str = "data/verbatim.db"
    sample_data_dir: str = "../sample_data"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    log_level: str = "INFO"
    log_json: bool = True

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
