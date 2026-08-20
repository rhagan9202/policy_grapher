from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/policy_grapher/config.py -> parents[3] is the repository root.
# In the container the layout differs and this path will not exist; pydantic-settings
# ignores a missing env_file, and compose supplies the variables directly.
REPO_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Backend configuration. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(env_file=REPO_ENV_FILE, extra="ignore")

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    # Deliberately non-functional: the password that used to live here was committed
    # to a public repository and is compromised (ADR-010 Decision 3). A default that
    # cannot authenticate fails loudly at startup instead of quietly working for the
    # one person who still has the old volume.
    neo4j_password: str = "set-me-run-scripts-init-env-sh"
    neo4j_database: str = "neo4j"

    graph_render_cap: int = 300
    query_row_cap: int = 1000
    query_timeout_seconds: float = 10.0

    # "name:sha256hex" pairs, comma-separated. Empty means nobody can authenticate.
    api_tokens: str = ""

    # Comma-separated origins. Empty means no cross-origin browser access.
    cors_allow_origins: str = "http://localhost:5173"

    # /openapi.json, /docs and /redoc carry no authentication of their own, so they
    # are off by default: publishing them would let an unauthenticated caller
    # enumerate every route. Turning this on is an explicit, documented opt-out.
    enable_api_docs: bool = False

    # Obligation extraction (DI-2 phase 3). The default adapter runs no model at
    # all, so a fresh clone and CI both pass without a model server; "local"
    # points at an Ollama-compatible HTTP endpoint. `extractor_model` is part of
    # the cache key via the adapter id — changing it must not reuse cached
    # results from a different model.
    extractor_adapter: str = "null"          # "null" | "local"
    extractor_model: str = "qwen3:8b"
    extractor_base_url: str = "http://localhost:11434"

    data_dir: Path = Path("/data/samples")
    sample_csv: str = "dod_policy_references_08122026.csv"
    auto_ingest: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
