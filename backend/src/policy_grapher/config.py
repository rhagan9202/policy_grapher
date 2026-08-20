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
    neo4j_password: str = "policygrapher"
    neo4j_database: str = "neo4j"

    graph_render_cap: int = 300
    query_row_cap: int = 1000
    query_timeout_seconds: float = 10.0

    # "name:sha256hex" pairs, comma-separated. Empty means nobody can authenticate.
    api_tokens: str = ""

    data_dir: Path = Path("/data/samples")
    sample_csv: str = "dod_policy_references_08122026.csv"
    auto_ingest: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
