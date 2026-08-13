import pytest
from neo4j import Driver
from testcontainers.community.neo4j import Neo4jContainer

from policy_grapher.config import Settings
from policy_grapher.db import apply_constraints, clear_graph, create_driver

NEO4J_IMAGE = "neo4j:2025.10"
TEST_PASSWORD = "testpassword"


@pytest.fixture(scope="session")
def neo4j_container():
    # Pass the password explicitly: Neo4jContainer otherwise picks up the host's
    # NEO4J_PASSWORD, which would silently couple tests to the developer's .env.
    with Neo4jContainer(NEO4J_IMAGE, password=TEST_PASSWORD) as container:
        yield container


@pytest.fixture(scope="session")
def database() -> str:
    return "neo4j"


@pytest.fixture(scope="session")
def settings_for_container(neo4j_container, database, tmp_path_factory) -> Settings:
    return Settings(
        _env_file=None,
        neo4j_uri=neo4j_container.get_connection_url(),
        neo4j_user=neo4j_container.username,
        neo4j_password=neo4j_container.password,
        neo4j_database=database,
        data_dir=tmp_path_factory.mktemp("data"),
        auto_ingest=False,
    )


@pytest.fixture(scope="session")
def driver(settings_for_container, database) -> Driver:
    drv = create_driver(settings_for_container)
    drv.verify_connectivity()
    apply_constraints(drv, database)
    yield drv
    drv.close()


@pytest.fixture
def clean_graph(driver, database) -> Driver:
    """Every integration test starts from an empty graph."""
    clear_graph(driver, database)
    return driver
