import os
import shutil
from fastapi.testclient import TestClient

# Make sure we use a clean test database
os.environ["TESTING"] = "1"

from main import app
from app.db import Base, engine, init_db
from app.services.database_service import DatabaseService
from sqlalchemy import text

# Re-init DB
with engine.begin() as connection:
    connection.execute(text("DROP TABLE IF EXISTS addresses_fts"))
Base.metadata.drop_all(bind=engine)
init_db()

print("\n=== VERIFICATION START ===")

with TestClient(app) as client:
    # Test 1: Upload clean invoice (140.pdf)
    # Should succeed via deterministic pipeline (regex path)
    print("\n[Test 1] Uploading clean invoice (140.pdf)...")
    pdf_path = os.path.join("sample_pdf2", "140.pdf")
    with open(pdf_path, "rb") as f:
        response = client.post("/extract", files={"file": ("invoice_5210_clean.pdf", f, "application/pdf")})

    print(f"Status: {response.status_code}")
    res_json = response.json()
    print("Response JSON:")
    print(res_json)
    clean_doc_id = res_json.get("document_id")
    print(f"Clean document ID: {clean_doc_id}")

    # Test 2: Upload messy invoice (185.txt)
    # Because it's messy, let's see what happens. If it fails, that's fine because it should.
    print("\n[Test 2] Uploading messy invoice (185.txt) via automatic regex pipeline...")
    txt_path = os.path.join("sample_pdf2", "185.txt")
    with open(txt_path, "rb") as f:
        response_txt = client.post("/extract", files={"file": ("invoice_5211_messy.txt", f, "text/plain")})

    print(f"Status: {response_txt.status_code}")
    res_txt_json = response_txt.json()
    print("Response JSON:")
    print(res_txt_json)
    messy_doc_id = res_txt_json.get("document_id")
    print(f"Messy document ID: {messy_doc_id}")

    # Test 3: Run LLM extraction on messy invoice (185.txt)
    print(f"\n[Test 3] Running LLM extraction on messy document ID {messy_doc_id}...")
    response_llm = client.post(f"/documents/{messy_doc_id}/extract_llm")
    print(f"Status: {response_llm.status_code}")
    res_llm_json = response_llm.json()
    print("Response JSON:")
    print(res_llm_json)

    # Test 4: Run LLM extraction on clean invoice (140.pdf)
    print(f"\n[Test 4] Running LLM extraction on clean document ID {clean_doc_id}...")
    response_llm_clean = client.post(f"/documents/{clean_doc_id}/extract_llm")
    print(f"Status: {response_llm_clean.status_code}")
    res_llm_clean_json = response_llm_clean.json()
    print("Response JSON:")
    print(res_llm_clean_json)

    # Test 5: Verify they map to the same normalized record in the database
    print("\n[Test 5] Checking unique addresses in database registry...")
    db_addresses = DatabaseService.list_addresses()
    print(f"Total unique addresses: {db_addresses['total']}")
    for i, item in enumerate(db_addresses["items"]):
        print(f"Address {i+1}: ID={item['id']}, Normalized='{item['normalized']}', Street='{item['street']}', Zip='{item['zip']}', review_status='{item['review_status']}'")

# Clean up
engine.dispose()
if os.path.exists("test_registry.db"):
    os.remove("test_registry.db")

print("\n=== VERIFICATION END ===")
