from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "policygrapher"
    neo4j_database: str = "neo4j"

    graph_render_cap: int = 300

    data_dir: Path = Path("/data")
    sample_csv: str = "dod_policy_references_08122026.csv"
    auto_ingest: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
