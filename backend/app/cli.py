"""Backward-compatible CLI interface"""

import os
import sys

from app.core.audio import record_audio
from app.core.config import settings
from app.core.ingestion import IngestionService, check_system_status
from app.core.query import QueryService
try:
    from pymilvus import utility  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover
    utility = None  # type: ignore[assignment]


def _ensure_api_keys() -> bool:
    if not settings.ASSEMBLYAI_API_KEY or not settings.OPENAI_API_KEY:
        print("\n❌ Missing API keys!")
        print("Please create a .env file with:")
        print("ASSEMBLYAI_API_KEY=your_key_here")
        print("OPENAI_API_KEY=your_key_here")
        return False
    return True


def _setup_system_if_needed() -> None:
    print("🔍 Checking system status...")
    try:
        if check_system_status():
            print("✅ System ready!")
            return

        print("\n⚠️ System not set up yet. Let's set it up first!")
        print("📡 Connecting to Milvus...")

        ingestion = IngestionService()
        ingestion.discover_files()
        ingestion.setup_vector_database()
        ingestion.process_multimodal_data()

        if ingestion.state.chunks:
            ingestion.generate_embeddings()
            ingestion.store_in_vector_database()
            print("✅ Setup completed!")
        else:
            print("⚠️ No data to process")

    except Exception as exc:  # pragma: no cover - defensive
        print(f"\n⚠️ Error checking system status: {exc}")
        print("Make sure Milvus is running: docker-compose up -d")


def _handle_text_query(service: QueryService) -> None:
    query = input("\n💬 Enter your question: ").strip()
    if not query:
        return
    print("\n🤔 Processing...")
    response = service.process_query(query)
    print(f"\n🤖 Response:\n{response}")


def _handle_audio_query(service: QueryService) -> None:
    duration = input("\n🎤 Recording duration in seconds (default 10): ").strip()
    duration_int = int(duration) if duration.isdigit() else 10

    audio_file = record_audio(duration_int)
    if not audio_file:
        return

    print("\n🤔 Processing...")
    response = service.process_query("", audio_file=audio_file)
    print(f"\n🤖 Response:\n{response}")

    try:
        os.unlink(audio_file)
    except Exception:
        pass


def _run_ingestion_pipeline() -> None:
    print("\n📥 Running ingestion pipeline...")

    # For metric/index changes (e.g. switching to COSINE), we must rebuild the collection
    # so Milvus uses the correct index configuration.
    try:
        if utility is not None and utility.has_collection(settings.COLLECTION_NAME):
            print("🧹 Dropping existing Milvus collection for rebuild...")
            utility.drop_collection(settings.COLLECTION_NAME)
    except Exception as exc:
        print(f"⚠️  Could not drop collection (continuing): {exc}")

    ingestion = IngestionService()
    ingestion.discover_files()
    ingestion.setup_vector_database()
    ingestion.process_multimodal_data()

    if ingestion.state.chunks:
        ingestion.generate_embeddings()
        ingestion.store_in_vector_database()
        print("✅ Ingestion completed!")
    else:
        print("⚠️ No data to process")


def main() -> None:
    print("\n🤖 Welcome to Multimodal Agentic RAG System!")
    print("=" * 50)

    if not _ensure_api_keys():
        return

    _setup_system_if_needed()

    service = QueryService()

    while True:
        print("\nWhat would you like to do?")
        print("1. 💬 Ask a question (text)")
        print("2. 🎤 Record and ask a question")
        print("3. � Re-ingest / Re-index data")
        print("4. �� Exit")

        choice = input("\nEnter your choice (1-4): ").strip()

        if choice == "1":
            _handle_text_query(service)
        elif choice == "2":
            _handle_audio_query(service)
        elif choice == "3":
            _run_ingestion_pipeline()
        elif choice == "4":
            print("\n👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice. Please enter 1-4.")


if __name__ == "__main__":  # pragma: no cover
    main()
