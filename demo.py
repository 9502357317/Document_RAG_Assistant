import os
import sys
import shutil
from pathlib import Path

# Ensure root folder is in path for imports
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT))


def reset_db():
    print("Resetting database and vector store...")

    # 1. Delete registry database file if it exists
    # We do this before importing any app modules to prevent file locking on Windows
    db_file = PROJECT_ROOT / "registry.db"
    if db_file.exists():
        try:
            db_file.unlink()
            print("Deleted registry.db")
        except Exception as e:
            print(f"Error deleting database file: {e}")

    # 2. Delete persistent ChromaDB directory
    chroma_dir = PROJECT_ROOT / "chroma_db"
    if chroma_dir.exists():
        try:
            shutil.rmtree(chroma_dir)
            print("Cleared chroma_db folder")
        except Exception as e:
            print(f"Error clearing Chroma folder: {e}")

    # 3. Import init_db and reinitialize database
    from app.db import init_db
    init_db()
    print("Database reset complete.")


def run_demo():
    # Reset DB on start
    reset_db()

    # Import app and TestClient now that database/vector store are clean
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)

    # Ingest the corpus via the /extract endpoint
    print("\n[Step 1] Ingesting corpus documents...")
    corpus_dir = PROJECT_ROOT / "corpus" / "corpus"
    if not corpus_dir.exists():
        corpus_dir = PROJECT_ROOT / "corpus"

    if not corpus_dir.exists():
        print("Error: Corpus directory not found!")
        sys.exit(1)

    for file_path in sorted(corpus_dir.glob("*")):
        if file_path.is_file():
            print(f"Ingesting file: {file_path.name}")
            with open(file_path, "rb") as f:
                res = client.post(
                    "/extract",
                    files={"file": (file_path.name, f.read(), "text/plain")}
                )
                if res.status_code not in (200, 409):
                    print(f"Failed to ingest {file_path.name}: {res.text}")

    # Run a full reindex to ensure markdown files are also indexed in the vector database
    print("\n[Step 1.5] Reindexing vector database to include all documents...")
    reindex_res = client.post("/rag/reindex")
    print(f"Status: {reindex_res.status_code}")
    print(reindex_res.json())

    # Print stats
    print("\n[Step 2] Querying database stats...")
    stats_res = client.get("/stats")
    print(f"Status: {stats_res.status_code}")
    print("Stats:")
    print(stats_res.json())

    # Run three RAG questions
    questions = [
        "What is the forwarding address in the DC letter?",
        "How many days do I have to return a standard item for a full refund?",
        "What port must be free to start the local Postgres container during onboarding?"
    ]

    print("\n[Step 3] Executing 3 Sample RAG Questions:")
    for i, q in enumerate(questions, 1):
        print(f"\nQuestion {i}: '{q}'")
        ask_res = client.post("/ask", json={"question": q})
        print(f"Status: {ask_res.status_code}")
        if ask_res.status_code == 200:
            data = ask_res.json()
            print("Response:")
            print(f"  Answer:  {data.get('answer')}")
            print(f"  Sources: {', '.join(data.get('sources', []))}")
        else:
            print("Response Error:")
            print(ask_res.text)


if __name__ == "__main__":
    run_demo()
