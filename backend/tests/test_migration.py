"""Migration regression tests.

These tests are lightweight placeholders to ensure that the new core
APIs for ingestion and querying can be invoked without errors. Full
bit-for-bit equality with the legacy implementation would require
mocking Milvus and OpenAI, which is outside the scope of this minimal
suite but can be added later.
"""

from backend.app.core.ingestion import IngestionService
from backend.app.core.query import QueryService


def test_ingestion_backward_compatibility_smoke() -> None:
    """Smoke-test that the new ingestion service can be instantiated.

    In a real regression test, this would compare Milvus contents before
    and after refactor for a fixed dataset.
    """

    service = IngestionService()
    assert service.state.discovered_files == []


def test_query_backward_compatibility_smoke() -> None:
    """Smoke-test that the new query service exposes process_query.

    This does not call external services; those should be mocked in a
    fuller regression suite.
    """

    service = QueryService()
    assert hasattr(service, "process_query")
