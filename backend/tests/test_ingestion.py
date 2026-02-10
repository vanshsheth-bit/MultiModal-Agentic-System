from backend.app.core.ingestion import DataIngestionState, generate_embeddings


def test_generate_embeddings_empty() -> None:
    state = DataIngestionState(chunks=[])
    new_state = generate_embeddings(state)
    assert new_state.chunks == []
