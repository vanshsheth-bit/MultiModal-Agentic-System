from backend.app.core.query import _format_search_results


def test_format_search_results_empty() -> None:
    assert _format_search_results([]) == "No relevant documents found."
