import os
import sys
import json
import pytest

# Ensure testing flag is set before any imports
os.environ["TESTING"] = "1"
os.environ["HF_TOKEN"] = "fake_hf_token_for_tests"

# Add root folder to sys.path
sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from fastapi.testclient import TestClient
from main import app
from app.db import Base, engine, init_db
from app.services.database_service import DatabaseService
from sqlalchemy import text


@pytest.fixture(autouse=True)
def clean_database(tmp_path, monkeypatch):
    """Ensure a fresh temporary database file and clean Chroma collection per test."""
    import app.db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Create a fresh temporary sqlite database file
    db_file = tmp_path / "test_temp_registry.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    # Create a new engine and sessionmaker
    test_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(
        bind=test_engine, autoflush=False, expire_on_commit=False
    )

    # Monkeypatch the engine and SessionLocal in app.db
    monkeypatch.setattr(app.db, "engine", test_engine)
    monkeypatch.setattr(app.db, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(app.db, "DATABASE_PATH", db_file)
    monkeypatch.setattr(app.db, "DATABASE_URL", db_url)

    # Monkeypatch references already imported at load-time in other modules
    monkeypatch.setattr("app.services.database_service.SessionLocal", TestSessionLocal)
    monkeypatch.setattr("app.services.rag_service.SessionLocal", TestSessionLocal)
    monkeypatch.setattr("app.api.routes.SessionLocal", TestSessionLocal)

    # Initialize the database schema and triggers on the fresh DB
    app.db.init_db()

    # Clear and reset the ChromaDB in-memory collection per test
    import app.services.rag_service
    try:
        app.services.rag_service.chroma_client.delete_collection("documents")
    except Exception:
        pass
    new_col = app.services.rag_service.chroma_client.get_or_create_collection("documents")
    monkeypatch.setattr(app.services.rag_service, "collection", new_col)

    yield

    # Clean up connections
    test_engine.dispose()
@pytest.fixture(autouse=True)
def mock_smarty(monkeypatch):
    """Mock Smarty API client to prevent network requests and billing errors."""
    class MockResponse:
        def __init__(self, json_data, status_code=200):
            self.json_data = json_data
            self.status_code = status_code
            self.text = json.dumps(json_data)

        def json(self):
            return self.json_data

    def fake_send_request(request_data):
        text = request_data.get("data", "")
        addresses = []

        if "123 Main St" in text:
            addresses.append({
                "text": "123 Main St, Columbus, OH 43215",
                "api_output": [{
                    "components": {
                        "primary_number": "123",
                        "street_name": "Main",
                        "street_suffix": "St",
                        "city_name": "Columbus",
                        "state_abbreviation": "OH",
                        "zipcode": "43215"
                    }
                }]
            })
        elif "1450 Industrial" in text:
            addresses.append({
                "text": "1450 Industrial Pkwy, Columbus, OH 43215",
                "api_output": [{
                    "components": {
                        "primary_number": "1450",
                        "street_name": "Industrial",
                        "street_suffix": "Pkwy",
                        "city_name": "Columbus",
                        "state_abbreviation": "OH",
                        "zipcode": "43215"
                    }
                }]
            })
        # ── Must check "Address A" / "Address B" BEFORE the generic "100 Main St" ──
        elif "Address A: 100 Main St" in text:
            addresses.append({
                "text": "100 Main St, Columbus, OH 43215",
                "api_output": [{
                    "components": {
                        "primary_number": "100",
                        "street_name": "Main",
                        "street_suffix": "St",
                        "city_name": "Columbus",
                        "state_abbreviation": "OH",
                        "zipcode": "43215"
                    }
                }]
            })
        elif "Address B: 100 Main St" in text:
            addresses.append({
                "text": "100 Main St, Columbus, OH 43216",
                "api_output": [{
                    "components": {
                        "primary_number": "100",
                        "street_name": "Main",
                        "street_suffix": "St",
                        "city_name": "Columbus",
                        "state_abbreviation": "OH",
                        "zipcode": "43216"
                    }
                }]
            })
        elif "100 Main St" in text or "100 Main Street" in text:
            addresses.append({
                "text": "100 Main St, Columbus, OH 43215",
                "api_output": [{
                    "components": {
                        "primary_number": "100",
                        "street_name": "Main",
                        "street_suffix": "St",
                        "city_name": "Columbus",
                        "state_abbreviation": "OH",
                        "zipcode": "43215"
                    }
                }]
            })

        return MockResponse({"addresses": addresses})

    monkeypatch.setattr("app.services.smarty_api_client.SmartyAPIClient.send_request", fake_send_request)


@pytest.fixture
def mock_llm(monkeypatch):
    """Mock LLM generate function where it is used in the codebase."""
    canned_responses = {
        "address_extraction": {
            "addresses": [
                {
                    "street": "1450 Industrial Pkwy",
                    "city": "Columbus",
                    "state": "OH",
                    "zip": "43215"
                }
            ]
        },
        "rag_answer_records": "The forwarding address is 1600 Pennsylvania Ave (Source: letter_dc.txt).",
        "rag_answer_unknown": "I don't know.",
    }

    def fake_generate(messages, max_tokens=1024):
        prompt_content = messages[-1]["content"] if messages else ""

        if "Extract EVERY postal address" in messages[0]["content"] or "Document Text:" in prompt_content:
            return json.dumps(canned_responses["address_extraction"])

        if "provided document context" in messages[0]["content"]:
            if "Office of Records" in prompt_content:
                return canned_responses["rag_answer_records"]
            return canned_responses["rag_answer_unknown"]

        return "Canned response"

    monkeypatch.setattr("app.services.llm_extractor.generate", fake_generate)
    monkeypatch.setattr("app.services.rag_service.generate", fake_generate)
    monkeypatch.setattr("app.api.routes.generate", fake_generate)


def test_root_endpoint():
    client = TestClient(app)
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/ask"


def test_deterministic_core_duplicate_file():
    client = TestClient(app)
    # Upload first time
    file_data = b"Hello address: 123 Main St, Columbus, OH 43215"
    response1 = client.post(
        "/extract", 
        files={"file": ("test_file.txt", file_data, "text/plain")}
    )
    assert response1.status_code == 200
    
    # Upload second time (exact duplicate content)
    response2 = client.post(
        "/extract", 
        files={"file": ("test_file.txt", file_data, "text/plain")}
    )
    assert response2.status_code == 409
    assert "already been uploaded" in response2.json()["error"]


def test_deterministic_core_address_variants_dedupe():
    client = TestClient(app)
    # First upload: Address format 1
    file_data1 = b"Billing: 1450 Industrial Pkwy, Columbus, OH 43215"
    res1 = client.post(
        "/extract",
        files={"file": ("clean1.txt", file_data1, "text/plain")}
    )
    assert res1.status_code == 200
    
    # Second upload: Address format 2 (same normalized address)
    file_data2 = b"Mail to: 1450 Industrial Parkway, Columbus, Ohio, zip 43215"
    res2 = client.post(
        "/extract",
        files={"file": ("clean2.txt", file_data2, "text/plain")}
    )
    assert res2.status_code == 200
    
    # Check that they normalized to the same address row and duplicate_addresses_caught incremented
    stats = DatabaseService.get_stats()
    assert stats["unique_addresses"] == 1
    assert stats["duplicate_addresses_caught"] == 1


def test_failed_extraction_stores_reason():
    client = TestClient(app)
    # Empty file triggers an extraction failure
    empty_file = b""
    res = client.post(
        "/extract",
        files={"file": ("empty.txt", empty_file, "text/plain")}
    )
    assert res.status_code == 400
    doc_id = res.json().get("document_id")
    assert doc_id is not None
    
    # Check database document status is failed
    doc = DatabaseService.get_document(doc_id)
    assert doc["status"] == "failed"
    assert "empty" in doc["failure_reason"].lower()


def test_merge_repoints_document_links():
    client = TestClient(app)
    
    # Upload address 1 (will be Winner)
    file_data1 = b"Address A: 100 Main St, Columbus, OH 43215"
    res1 = client.post("/extract", files={"file": ("file1.txt", file_data1, "text/plain")})
    addr1_id = res1.json()["address_ids"][0]
    
    # Upload address 2 (will be Loser)
    file_data2 = b"Address B: 100 Main St, Columbus, OH 43216"
    res2 = client.post("/extract", files={"file": ("file2.txt", file_data2, "text/plain")})
    addr2_id = res2.json()["address_ids"][0]
    
    # They should trigger a duplicate candidate
    dupes = DatabaseService.list_duplicates()
    assert len(dupes) > 0
    dupe_id = dupes[0]["id"]
    
    # Resolve merge: Winner = addr1_id, Loser = addr2_id
    resolve_data = {
        "action": "merge",
        "winning_address_id": addr1_id
    }
    res_merge = client.post(f"/duplicates/{dupe_id}/resolve", json=resolve_data)
    assert res_merge.status_code == 200
    
    # Verify that Loser is merged and document links are re-pointed
    loser_addr = DatabaseService.get_address(addr2_id)
    assert loser_addr["review_status"] == "merged"
    
    winner_addr = DatabaseService.get_address(addr1_id)
    # Winner should now contain links to BOTH documents
    doc_ids = [doc["id"] for doc in winner_addr["documents"]]
    assert len(doc_ids) == 2


def test_rag_reindex():
    client = TestClient(app)
    res = client.post("/rag/reindex")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["total_chunks"] > 0


def test_rag_search_no_rerank():
    client = TestClient(app)
    # Index first
    client.post("/rag/reindex")
    
    res = client.post(
        "/rag/search", 
        json={"question": "Office of Records notice", "k": 2, "rerank": False}
    )
    assert res.status_code == 200
    results = res.json()
    assert len(results) == 2
    assert "score" in results[0]
    assert "filename" in results[0]


def test_rag_ask_endpoint(mock_llm):
    client = TestClient(app)
    client.post("/rag/reindex")
    
    # Question that yields a mocked answer
    res = client.post(
        "/ask",
        json={"question": "What forwarding address does the Office of Records notice give for future mail?"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["context_found"] is True
    assert "1600 Pennsylvania Ave" in data["answer"]
    assert "letter_dc.txt" in data["sources"]


def test_rag_ask_endpoint_refusal(mock_llm):
    client = TestClient(app)
    client.post("/rag/reindex")
    
    # Question that triggers refusal
    res = client.post(
        "/ask",
        json={"question": "What is the Wi-Fi password for the Tokyo office?"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["context_found"] is False
    assert data["answer"] == "I don't know."
    assert len(data["sources"]) == 0


def test_extract_llm_success(monkeypatch):
    client = TestClient(app)
    # Upload document
    file_data = b"Billing: 1450 Industrial Pkwy, Columbus, OH 43215"
    res = client.post("/extract", files={"file": ("test_llm.txt", file_data, "text/plain")})
    assert res.status_code == 200
    doc_id = res.json()["document_id"]
    
    # Mock LLM to return valid address on first try
    canned = {
        "addresses": [
            {
                "street": "1450 Industrial Pkwy",
                "city": "Columbus",
                "state": "OH",
                "zip": "43215"
            }
        ]
    }
    monkeypatch.setattr("app.services.llm_extractor.generate", lambda m, max_tokens=1024: json.dumps(canned))
    
    res_llm = client.post(f"/documents/{doc_id}/extract_llm")
    assert res_llm.status_code == 200
    data = res_llm.json()
    assert data["success"] is True
    assert data["extraction_path"] == "llm"
    assert len(data["addresses"]) == 1
    assert data["addresses"][0]["street"] == "1450 Industrial Pkwy"


def test_extract_llm_retry(monkeypatch):
    client = TestClient(app)
    file_data = b"Billing: 1450 Industrial Pkwy, Columbus, OH 43215"
    res = client.post("/extract", files={"file": ("test_llm_retry.txt", file_data, "text/plain")})
    assert res.status_code == 200
    doc_id = res.json()["document_id"]
    
    # Mock LLM to fail first, succeed on second (retry)
    call_count = 0
    canned = {
        "addresses": [
            {
                "street": "1450 Industrial Pkwy",
                "city": "Columbus",
                "state": "OH",
                "zip": "43215"
            }
        ]
    }
    def fake_generate(messages, max_tokens=1024):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "garbled response"
        return json.dumps(canned)
        
    monkeypatch.setattr("app.services.llm_extractor.generate", fake_generate)
    
    res_llm = client.post(f"/documents/{doc_id}/extract_llm")
    assert res_llm.status_code == 200
    data = res_llm.json()
    assert data["success"] is True
    assert data["extraction_path"] == "llm_retry"
    assert len(data["addresses"]) == 1
    assert data["addresses"][0]["street"] == "1450 Industrial Pkwy"


def test_extract_llm_fallback(monkeypatch):
    client = TestClient(app)
    file_data = b"Address fallback: 100 Main St, Columbus, OH 43215"
    res = client.post("/extract", files={"file": ("test_llm_fallback.txt", file_data, "text/plain")})
    assert res.status_code == 200
    doc_id = res.json()["document_id"]
    
    # Mock LLM to fail both times
    monkeypatch.setattr("app.services.llm_extractor.generate", lambda m, max_tokens=1024: "garbled response")
    
    res_llm = client.post(f"/documents/{doc_id}/extract_llm")
    assert res_llm.status_code == 200
    data = res_llm.json()
    assert data["success"] is True
    assert data["extraction_path"] == "fallback_regex"
    assert len(data["addresses"]) == 1
    assert data["addresses"][0]["street"] == "Main"



