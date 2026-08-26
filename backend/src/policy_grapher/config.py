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
    # An edition's obligation list (STORY-081). Sized against the corpus rather
    # than guessed: the largest edition in `data/samples` is 204 chunks, and the
    # 37-chunk edition rebuilt on 2026-08-25 yielded 113 obligations — roughly
    # three per chunk, so 204 chunks lands near 600. This caps well above any
    # edition in the sample corpus while still bounding a pathological one.
    obligation_list_cap: int = 800
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
    # Llama 3.1 (Meta, US). Model provenance is a procurement constraint here, not
    # a preference — see ADR-020. Capable non-US models such as Qwen and DeepSeek
    # are ineligible regardless of how they score.
    extractor_model: str = "llama3.1:8b"
    extractor_base_url: str = "http://localhost:11434"
    # Per model call, not per rebuild. 120s was hardcoded in extraction/local.py until
    # sprint 4's walkthrough hit it: a rebuild of DoDD 5000.01 died on chunk 1 of 34
    # with httpx.ReadTimeout on a CPU-only host measured at ~7 tokens/second. The
    # reasoning already written on `rebuild_job_timeout_seconds` applies here too —
    # with a real model there is no short timeout that is not a false alarm — and it
    # had been applied to the job but not to the HTTP call inside it (STORY-058).
    extractor_timeout_seconds: float = 600.0

    # Embedding (DI-2 phase 6). "null" produces no vectors and needs no model —
    # the default, so a fresh clone and CI pass without a download. "local" runs
    # a sentence-transformers model on this machine; hosted is deliberately not
    # an option (ADR-016). `embedder_model` is recorded on the vector index, and
    # a later run under a different one is refused rather than silently mixed.
    embedder_adapter: str = "null"          # "null" | "local"
    # Snowflake Inc. (US), Apache 2.0, 384 dimensions — the same index width as the
    # `all-MiniLM-L6-v2` it replaces, which was published by UKP Lab at TU Darmstadt
    # and therefore never met ADR-020's provenance bar. ADR-020 governed extraction
    # only and named this as the gap to check first; STORY-060's audit checked it.
    # Changed while nothing was embedded, which is the only moment it is free
    # (ADR-016 makes a later change a corpus re-embed). See ADR-024.
    embedder_model: str = "Snowflake/snowflake-arctic-embed-s"

    # The rebuild queue (STORY-048). Unreachable Redis fails only the rebuild
    # routes — the connection is lazy and every other route talks to Neo4j.
    redis_url: str = "redis://localhost:6379/0"
    # Eight hours, and the size is the whole point. A rebuild with a real model is
    # one extraction call per chunk, measured at ~104 seconds a chunk on CPU; the
    # largest edition in `data/samples` is 204 chunks, so a first pass over it needs
    # close to six hours. This was 1800 — thirty minutes, under three chunks' worth
    # of the margin it claimed to have — and every edition in the corpus exceeded
    # it. A real run of DoDD 5000.01 died at chunk 30 of 37 and wrote nothing.
    #
    # A job timeout is not the thing that catches a hung model here:
    # `extractor_timeout_seconds` bounds each individual call, so a wedged Ollama
    # surfaces in ten minutes regardless. What is left for this number to do is bound
    # total work, and bounding it below the work's honest duration only ever produces
    # false alarms. `test_the_job_timeout_outlasts_the_largest_edition_in_the_corpus`
    # measures the corpus rather than trusting this comment.
    rebuild_job_timeout_seconds: int = 28800
    # Longer than the job timeout above, deliberately, and one day still leaves
    # three times the margin: the result is the only record of what a run
    # produced. RQ's 500-second default would expire a legitimate run's counts
    # minutes after they landed, and the poll route would then answer 404 —
    # indistinguishable from a run id that never existed. One day is long enough
    # for a person to start an overnight rebuild and read it in the morning.
    # `test_the_result_outlives_the_run_that_produced_it` keeps the ordering.
    rebuild_result_ttl_seconds: int = 86400

    data_dir: Path = Path("/data/samples")
    sample_csv: str = "dod_policy_references_08122026.csv"
    # Off by default (ADR-019). A first run holds nothing, and every screen
    # explains that rather than rendering a blank that reads as failure. The
    # machinery still works when this is switched on — a changed default, not a
    # removal.
    auto_ingest: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
