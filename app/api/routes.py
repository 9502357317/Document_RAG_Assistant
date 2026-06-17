import logging
import csv
import io
import hashlib
import re
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.services.address_service import AddressService
from app.services.database_service import DatabaseService
from app.services.file_reader import FileParser
from app.services.llm import generate
from app.services.llm_extractor import extract_addresses_with_llm
from app.db import SessionLocal
from app.models.database_models import Document

router = APIRouter()
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Pydantic Schemas for Request Validation
# -----------------------------------------------------------------------------

class AddressPatch(BaseModel):
    """Schema for patching specific fields of an address."""
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    review_status: str | None = None


class ResolveDuplicate(BaseModel):
    """Schema for resolving duplicate candidates."""
    action: str  # Must be "merge" or "not_duplicate"
    winning_address_id: int | None = None  # Required only when action is "merge"


class ExtractController:
    @staticmethod
    def format_response(
        addresses: list,
        document_id: int,
        address_results: list[dict],
        extraction_path: str = "regex"
    ) -> dict:
        new_address_count = sum(1 for item in address_results if item["is_new"])
        existing_address_count = sum(1 for item in address_results if not item["is_new"])

        return {
            "success": True,
            "document_id": document_id,
            "extraction_path": extraction_path,
            "address_ids": [item["id"] for item in address_results],
            "count": len(addresses),
            "new_address_count": new_address_count,
            "existing_address_count": existing_address_count,
            "addresses": [
                {
                    "id": address_results[index]["id"],
                    "is_new": address_results[index]["is_new"],
                    "dedupe_status": "new" if address_results[index]["is_new"] else "existing",
                    "input_text": address.input_text,
                    "components": {
                        "primary_number": address.components.primary_number,
                        "street_name": address.components.street_name,
                        "street_suffix": address.components.street_suffix,
                        "city_name": address.components.city_name,
                        "state_abbreviation": address.components.state_abbreviation,
                        "zipcode": address.components.zipcode,
                    },
                }
                for index, address in enumerate(addresses)
            ],
        }

    @staticmethod
    def extract(request: UploadFile) -> JSONResponse:
        file_details = DatabaseService.get_file_details(request)

        # 1. Byte-level duplicate check (SHA-256)
        existing = DatabaseService.get_document_by_sha256(file_details["sha256"])

        if existing:
            DatabaseService.record_duplicate_file_rejected(
                file_details=file_details,
                existing_document_id=existing.id,
            )
            logger.warning(
                "Duplicate upload rejected: filename=%s existing_id=%s",
                file_details["filename"],
                existing.id,
            )
            return JSONResponse(
                status_code=409,
                content={
                    "success": False,
                    "error": "This file has already been uploaded.",
                    "existing_document_id": existing.id,
                    "uploaded_at": existing.uploaded_at.isoformat(),
                },
            )

        # 2. Extract text and validate early
        from app.services.file_validator import FileValidator
        try:
            FileValidator.validate_file_type(request)
            FileValidator.validate_file_size(request)
            text = FileParser.read_file(request)
            FileValidator.validate_empty_file(text)

            if len(text.encode("utf-8")) > 10 * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail="The file is too large to process. Please upload a smaller document."
                )

            # Compute content-level hash
            text_lowercased = text.lower()
            collapsed = re.sub(r'\s+', ' ', text_lowercased).strip()
            content_hash = hashlib.sha256(collapsed.encode("utf-8")).hexdigest()

            # Check for content-level duplicate
            existing_content = DatabaseService.get_document_by_content_hash(content_hash)
            if existing_content:
                DatabaseService.record_duplicate_file_rejected(
                    file_details=file_details,
                    existing_document_id=existing_content.id,
                )
                logger.warning(
                    "Duplicate content upload rejected: filename=%s existing_id=%s",
                    file_details["filename"],
                    existing_content.id,
                )
                return JSONResponse(
                    status_code=409,
                    content={
                        "success": False,
                        "error": "This file has already been uploaded.",
                        "existing_document_id": existing_content.id,
                        "uploaded_at": existing_content.uploaded_at.isoformat(),
                    },
                )

        except HTTPException as error:
            document_id = DatabaseService.create_document(file_details)
            DatabaseService.mark_document_failed(document_id, error.detail)
            return JSONResponse(
                status_code=error.status_code,
                content={"success": False, "document_id": document_id, "error": error.detail},
            )
        except Exception as e:
            logger.exception("Unexpected error during pre-validation")
            document_id = DatabaseService.create_document(file_details)
            DatabaseService.mark_document_failed(document_id, "Unexpected server error during pre-validation.")
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "document_id": document_id,
                    "error": "Something went wrong on server. Please try again later.",
                },
            )

        # 3. Create document row in database
        document_id = DatabaseService.create_document(file_details)

        # Wire ingestion into upload pipeline so new documents are embedded automatically
        try:
            from app.services.rag_service import rag_service
            rag_service.index_document(file_details["filename"], text)
        except Exception as index_err:
            logger.error(f"Error indexing uploaded document {file_details['filename']}: {index_err}")

        try:
            # Process using deterministic path
            addresses = AddressService.process_text(text)

            address_results = DatabaseService.save_extracted_addresses(
                document_id=document_id,
                extracted_addresses=addresses,
                content_hash=content_hash,
                raw_text=text,
                extraction_path="regex"
            )

            logger.info(
                "Document processed: document_id=%s filename=%s",
                document_id,
                file_details["filename"],
            )

            return JSONResponse(
                status_code=200,
                content=ExtractController.format_response(
                    addresses=addresses,
                    document_id=document_id,
                    address_results=address_results,
                    extraction_path="regex"
                ),
            )

        except HTTPException as error:
            # Save the raw text so extract_llm can be run later if desired
            DatabaseService.mark_document_failed(
                document_id=document_id,
                reason=str(error.detail),
            )
            # Also save raw text to document row even on failure
            with SessionLocal() as session:
                doc_row = session.get(Document, document_id)
                if doc_row:
                    doc_row.raw_text = text
                    session.commit()

            logger.warning(
                "Document extraction failed: document_id=%s reason=%s",
                document_id,
                error.detail,
            )

            return JSONResponse(
                status_code=error.status_code,
                content={
                    "success": False,
                    "document_id": document_id,
                    "error": error.detail,
                },
            )

        except Exception as e:
            DatabaseService.mark_document_failed(
                document_id=document_id,
                reason="Unexpected server error during extraction.",
            )
            with SessionLocal() as session:
                doc_row = session.get(Document, document_id)
                if doc_row:
                    doc_row.raw_text = text
                    session.commit()

            logger.exception("Unexpected extraction failure: document_id=%s", document_id)
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "document_id": document_id,
                    "error": "Something went wrong on server. Please try again later.",
                },
            )


@router.post("/extract")
async def extract_endpoint(file: UploadFile = File(...)):
    """Upload one file and extract/deduplicate addresses using deterministic pipeline."""
    return ExtractController.extract(file)


@router.post("/documents/{document_id}/extract_llm")
def extract_llm_endpoint(document_id: int):
    """
    Opt-in LLM address extraction.
    Loads raw text of document, extracts addresses with LLM, validates,
    retries once on failure, falls back to regex on double failure,
    saves addresses to the DB, and returns validated JSON addresses.
    """
    document = DatabaseService.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    raw_text = document.get("raw_text")
    if not raw_text:
        raise HTTPException(
            status_code=400,
            detail="No text available for this document to extract."
        )

    # Run LLM extraction service
    addresses, path_taken = extract_addresses_with_llm(raw_text)

    # Save addresses to registry db
    text_lowercased = raw_text.lower()
    collapsed = re.sub(r'\s+', ' ', text_lowercased).strip()
    content_hash = hashlib.sha256(collapsed.encode("utf-8")).hexdigest()

    address_results = DatabaseService.save_extracted_addresses(
        document_id=document_id,
        extracted_addresses=addresses,
        content_hash=content_hash,
        raw_text=raw_text,
        extraction_path=path_taken
    )

    return {
        "success": True,
        "document_id": document_id,
        "extraction_path": path_taken,
        "addresses": [
            {
                "street": addr.components.street_name if addr.components.street_name else addr.input_text.split(",")[0].strip(),
                "city": addr.components.city_name,
                "state": addr.components.state_abbreviation,
                "zip": addr.components.zipcode
            }
            for addr in addresses
        ]
    }


@router.get("/documents")
def list_documents(status: str | None = None):
    if status not in (None, "processed", "failed"):
        raise HTTPException(status_code=400, detail="Status must be processed or failed.")
    return DatabaseService.list_documents(status)


@router.get("/documents/{document_id}")
def get_document(document_id: int):
    document = DatabaseService.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.get("/addresses")
def list_addresses(
    limit: int = 20,
    offset: int = 0,
    search: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip: str | None = None,
):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 100.")
    if offset < 0:
        raise HTTPException(status_code=400, detail="Offset must be 0 or greater.")
    return DatabaseService.list_addresses(
        limit=limit,
        offset=offset,
        search=search,
        city=city,
        state=state,
        zip=zip,
    )


@router.get("/addresses/filter-options")
def get_filter_options():
    return DatabaseService.get_filter_options()


@router.patch("/addresses/{address_id}")
def patch_address(address_id: int, patch_data: AddressPatch):
    address = DatabaseService.patch_address(
        address_id=address_id,
        data=patch_data.model_dump(exclude_unset=True)
    )
    if address is None:
        raise HTTPException(status_code=404, detail="Address not found.")
    return address


@router.get("/duplicates")
def list_duplicates():
    return DatabaseService.list_duplicates()


@router.post("/duplicates/{duplicate_id}/resolve")
def resolve_duplicate(duplicate_id: int, resolve_data: ResolveDuplicate):
    if resolve_data.action not in ("merge", "not_duplicate"):
        raise HTTPException(status_code=400, detail="Action must be merge or not_duplicate.")
    if resolve_data.action == "merge" and not resolve_data.winning_address_id:
        raise HTTPException(status_code=400, detail="winning_address_id is required for merge.")

    success = DatabaseService.resolve_duplicate(
        duplicate_id=duplicate_id,
        action=resolve_data.action,
        winning_address_id=resolve_data.winning_address_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Duplicate candidate not found.")
    return {"success": True, "message": "Duplicate candidate resolved."}


@router.get("/addresses/{address_id}")
def get_address(address_id: int):
    address = DatabaseService.get_address(address_id)
    if address is None:
        raise HTTPException(status_code=404, detail="Address not found.")
    return address


@router.delete("/addresses/{address_id}")
def delete_address(address_id: int):
    deleted = DatabaseService.soft_delete_address(address_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Address not found.")
    return {"success": True, "address_id": address_id, "message": "Address soft-deleted."}


@router.get("/stats")
def get_stats():
    return DatabaseService.get_stats()


@router.get("/export")
def export_addresses(
    format: str = "csv",
    search: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip: str | None = None,
):
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only CSV export format is supported.")

    def generate_csv_rows():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "raw_text", "normalized", "street", "city", "state", "zip", "review_status", "created_at"])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        from app.db import SessionLocal
        from app.models.database_models import Address as AddressRecord
        from sqlalchemy import select, or_, text

        with SessionLocal() as session:
            filters = [
                AddressRecord.deleted_at.is_(None),
                or_(AddressRecord.review_status != "merged", AddressRecord.review_status.is_(None))
            ]

            if search:
                words = [w.strip() for w in search.strip().split() if w.strip()]
                if words:
                    escaped_words = [w.replace('"', '""') for w in words]
                    fts_query = " ".join(f'"{ew}"*' for ew in escaped_words)
                    fts_subquery = (
                        select(text("address_id"))
                        .select_from(text("addresses_fts"))
                        .where(text("addresses_fts MATCH :query").bindparams(query=fts_query))
                    )
                    filters.append(AddressRecord.id.in_(fts_subquery))

            if city:
                filters.append(AddressRecord.city == city.strip().upper())
            if state:
                filters.append(AddressRecord.state == state.strip().upper())
            if zip:
                filters.append(AddressRecord.zip == zip.strip())

            statement = select(AddressRecord).where(*filters).order_by(AddressRecord.created_at.desc())
            addresses = session.scalars(statement).all()

            for address in addresses:
                writer.writerow([
                    address.id,
                    address.raw_text,
                    address.normalized,
                    address.street,
                    address.city,
                    address.state,
                    address.zip,
                    address.review_status,
                    address.created_at.isoformat() if address.created_at else ""
                ])
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

    return StreamingResponse(
        generate_csv_rows(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=exported_addresses.csv"}
    )


@router.get("/test-llm")
def test_llm():
    response = generate([
        {"role": "user", "content": "Say Hello"}
    ])
    return {"response": response}


# -----------------------------------------------------------------------------
# RAG endpoints & Front-end UI
# -----------------------------------------------------------------------------

class SearchRequest(BaseModel):
    question: str
    k: int = 4
    rewrite: bool = False
    rerank: bool = True

class AskRequest(BaseModel):
    question: str
    rewrite: bool = False

class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    context_found: bool


@router.post("/rag/reindex")
def reindex_endpoint():
    """Reindexes all files in the corpus directory."""
    try:
        from app.services.rag_service import rag_service, PROJECT_ROOT
        
        # Locate corpus folder
        corpus_dir = PROJECT_ROOT / "corpus" / "corpus"
        if not corpus_dir.exists():
            corpus_dir = PROJECT_ROOT / "corpus"
        
        if not corpus_dir.exists():
            raise HTTPException(status_code=500, detail="Corpus directory not found.")
            
        indexed_files = 0
        for file_path in corpus_dir.glob("*"):
            if file_path.is_file():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    rag_service.index_document(file_path.name, content)
                    indexed_files += 1
                except Exception as file_err:
                    logger.error(f"Error reading/indexing {file_path.name}: {file_err}")
        
        total_chunks = rag_service.get_total_chunks()
        return {
            "success": True,
            "indexed_files": indexed_files,
            "total_chunks": total_chunks
        }
    except Exception as e:
        logger.exception("Reindexing failed:")
        raise HTTPException(status_code=500, detail=f"Reindexing failed: {e}")


@router.post("/rag/search")
def search_endpoint(request: SearchRequest):
    """Similarity search for the top-k chunks, optionally with cross-encoder reranking."""
    try:
        from app.services.rag_service import rag_service
        
        if request.rerank:
            candidates = rag_service.search(request.question, k=20, rewrite=request.rewrite)
            results = rag_service.rerank(request.question, candidates, k=request.k)
        else:
            results = rag_service.search(request.question, k=request.k, rewrite=request.rewrite)
            
        return results
    except Exception as e:
        logger.exception("RAG search failed:")
        raise HTTPException(status_code=500, detail=f"RAG search failed: {e}")


@router.post("/ask", response_model=AskResponse)
def ask_endpoint(request: AskRequest):
    """Full RAG Q&A endpoint."""
    try:
        from app.services.rag_service import rag_service
        res = rag_service.ask(request.question, rewrite=request.rewrite)
        return AskResponse(**res)
    except Exception as e:
        logger.exception("RAG Q&A failed:")
        raise HTTPException(status_code=500, detail=f"RAG Q&A failed: {e}")


@router.get("/rag/history")
def get_rag_history(limit: int = 10):
    """Retrieve the most recent RAG Q&A logs."""
    try:
        return DatabaseService.list_rag_logs(limit=limit)
    except Exception as e:
        logger.exception("Failed to retrieve RAG history:")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve RAG history: {e}")


from fastapi.responses import HTMLResponse

@router.get("/ask", response_class=HTMLResponse)
def ask_ui():
    """Serve a modern, responsive glassmorphic HTML UI for the Q&A box."""
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAG Assistant</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(17, 25, 40, 0.65);
            --border-color: rgba(255, 255, 255, 0.08);
            --primary-glow: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
            --text-color: #f3f4f6;
            --text-muted: #9ca3af;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            background-image: 
                radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.15) 0, transparent 50%),
                radial-gradient(at 100% 100%, rgba(139, 92, 246, 0.15) 0, transparent 50%);
            overflow-x: hidden;
            padding: 2rem;
        }
        .container {
            width: 100%;
            max-width: 750px;
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 3rem;
            box-shadow: 0 20px 40px rgba(0,0,0,0.3);
            position: relative;
        }
        .container::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            border-radius: 24px;
            padding: 2px;
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.3), rgba(139, 92, 246, 0.3), transparent, transparent);
            -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
            -webkit-mask-composite: xor;
            mask-composite: exclude;
            pointer-events: none;
        }
        h1 {
            font-size: 2.5rem;
            font-weight: 800;
            margin-bottom: 0.5rem;
            background: var(--primary-glow);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-align: center;
        }
        .subtitle {
            text-align: center;
            color: var(--text-muted);
            margin-bottom: 2.5rem;
            font-size: 1rem;
        }
        .form-group {
            margin-bottom: 1.5rem;
            position: relative;
        }
        textarea {
            width: 100%;
            height: 120px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            color: var(--text-color);
            padding: 1rem 1.25rem;
            font-size: 1.1rem;
            font-family: inherit;
            resize: none;
            outline: none;
            transition: all 0.3s ease;
        }
        textarea:focus {
            border-color: #3b82f6;
            box-shadow: 0 0 15px rgba(59, 130, 246, 0.25);
            background: rgba(255, 255, 255, 0.05);
        }
        .options-row {
            display: flex;
            justify-content: flex-end;
            align-items: center;
            margin-bottom: 1.5rem;
        }
        .switch-label {
            display: flex;
            align-items: center;
            cursor: pointer;
            color: var(--text-muted);
            font-size: 0.95rem;
            user-select: none;
        }
        .switch-label input { display: none; }
        .switch-toggle {
            width: 44px;
            height: 24px;
            background-color: rgba(255,255,255,0.1);
            border-radius: 12px;
            margin-left: 10px;
            position: relative;
            transition: background-color 0.3s;
        }
        .switch-toggle::before {
            content: '';
            width: 18px;
            height: 18px;
            background-color: white;
            border-radius: 50%;
            position: absolute;
            top: 3px;
            left: 3px;
            transition: transform 0.3s;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        .switch-label input:checked + .switch-toggle {
            background: var(--primary-glow);
        }
        .switch-label input:checked + .switch-toggle::before {
            transform: translateX(20px);
        }
        button {
            width: 100%;
            padding: 1rem;
            border: none;
            border-radius: 16px;
            background: var(--primary-glow);
            color: white;
            font-size: 1.1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(139, 92, 246, 0.2);
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(139, 92, 246, 0.35);
        }
        button:active { transform: translateY(0); }
        .loader {
            display: none;
            justify-content: center;
            align-items: center;
            margin: 2rem 0 0 0;
        }
        .spinner {
            width: 40px;
            height: 40px;
            border: 4px solid rgba(255,255,255,0.05);
            border-top-color: #8b5cf6;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .result-card {
            display: none;
            margin-top: 2.5rem;
            padding: 2rem;
            background: rgba(255,255,255,0.02);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            animation: fadeIn 0.5s ease;
        }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .result-title {
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--text-muted);
            margin-bottom: 0.75rem;
            font-weight: 600;
        }
        .result-answer {
            font-size: 1.15rem;
            line-height: 1.6;
            margin-bottom: 1.5rem;
            color: #f3f4f6;
        }
        .sources-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            align-items: center;
        }
        .source-chip {
            padding: 0.4rem 0.8rem;
            background: rgba(59, 130, 246, 0.15);
            border: 1px solid rgba(59, 130, 246, 0.3);
            color: #60a5fa;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
        }
        .status-chip {
            display: inline-block;
            padding: 0.25rem 0.6rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            margin-bottom: 1rem;
        }
        .status-found {
            background-color: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }
        .status-not-found {
            background-color: rgba(245, 158, 11, 0.15);
            color: #fbbf24;
            border: 1px solid rgba(245, 158, 11, 0.3);
        }
        .history-section {
            margin-top: 3rem;
            border-top: 1px solid var(--border-color);
            padding-top: 2rem;
        }
        .history-title {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            background: var(--primary-glow);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-align: left;
        }
        .history-item {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.25rem;
            margin-bottom: 1rem;
            transition: all 0.3s ease;
            text-align: left;
        }
        .history-item:hover {
            background: rgba(255, 255, 255, 0.04);
            border-color: rgba(59, 130, 246, 0.2);
            transform: translateY(-2px);
        }
        .history-question {
            font-weight: 600;
            font-size: 1.05rem;
            margin-bottom: 0.5rem;
            color: #f3f4f6;
        }
        .history-answer {
            font-size: 0.95rem;
            line-height: 1.5;
            color: var(--text-muted);
            margin-bottom: 0.75rem;
        }
        .history-meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.8rem;
            color: rgba(156, 163, 175, 0.6);
        }
        .history-sources {
            display: flex;
            gap: 0.4rem;
        }
        .history-source-chip {
            padding: 0.2rem 0.5rem;
            background: rgba(59, 130, 246, 0.15);
            border: 1px solid rgba(59, 130, 246, 0.3);
            color: #60a5fa;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Document RAG Assistant</h1>
        <div class="subtitle">Ask questions about retention policies, normalizations, incidents, and invoices</div>
        
        <div class="form-group">
            <textarea id="question" placeholder="E.g., What forwarding address does the Office of Records notice give for future mail?"></textarea>
        </div>
        
        <div class="options-row">
            <label class="switch-label">
                Query Rewriting
                <input type="checkbox" id="rewrite">
                <span class="switch-toggle"></span>
            </label>
        </div>
        
        <button id="ask-btn">Ask Question</button>
        
        <div class="loader" id="loader">
            <div class="spinner"></div>
        </div>
        
        <div class="result-card" id="result-card">
            <span class="status-chip" id="status-badge">Context Found</span>
            <div class="result-title">Answer</div>
            <div class="result-answer" id="result-answer"></div>
            
            <div class="result-title">Sources used</div>
            <div class="sources-row" id="sources-container"></div>
        </div>

        <!-- History Section -->
        <div class="history-section" id="history-section" style="display: none;">
            <div class="history-title">Recent Q&A History</div>
            <div id="history-list"></div>
        </div>
    </div>

    <script>
        const askBtn = document.getElementById('ask-btn');
        const questionInput = document.getElementById('question');
        const rewriteCheckbox = document.getElementById('rewrite');
        const loader = document.getElementById('loader');
        const resultCard = document.getElementById('result-card');
        const resultAnswer = document.getElementById('result-answer');
        const sourcesContainer = document.getElementById('sources-container');
        const statusBadge = document.getElementById('status-badge');
        const historySection = document.getElementById('history-section');
        const historyList = document.getElementById('history-list');

        async function loadHistory() {
            try {
                const response = await fetch('/rag/history?limit=5');
                if (!response.ok) return;
                const logs = await response.json();
                
                if (logs.length > 0) {
                    historySection.style.display = 'block';
                    historyList.innerHTML = '';
                    
                    logs.forEach(log => {
                        const item = document.createElement('div');
                        item.className = 'history-item';
                        
                        const qDiv = document.createElement('div');
                        qDiv.className = 'history-question';
                        qDiv.innerText = log.question;
                        item.appendChild(qDiv);
                        
                        const aDiv = document.createElement('div');
                        aDiv.className = 'history-answer';
                        aDiv.innerText = log.answer;
                        item.appendChild(aDiv);
                        
                        const metaDiv = document.createElement('div');
                        metaDiv.className = 'history-meta';
                        
                        const sourcesDiv = document.createElement('div');
                        sourcesDiv.className = 'history-sources';
                        if (log.sources && log.sources.length > 0) {
                            log.sources.forEach(src => {
                                const chip = document.createElement('span');
                                chip.className = 'history-source-chip';
                                chip.innerText = src;
                                sourcesDiv.appendChild(chip);
                            });
                        } else {
                            const noneSpan = document.createElement('span');
                            noneSpan.style.color = 'rgba(156, 163, 175, 0.4)';
                            noneSpan.innerText = 'No sources';
                            sourcesDiv.appendChild(noneSpan);
                        }
                        metaDiv.appendChild(sourcesDiv);
                        
                        const timeSpan = document.createElement('span');
                        const date = new Date(log.created_at + 'Z');
                        const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                        timeSpan.innerText = `${timeStr} (${Math.round(log.latency_ms)}ms)`;
                        metaDiv.appendChild(timeSpan);
                        
                        item.appendChild(metaDiv);
                        historyList.appendChild(item);
                    });
                } else {
                    historySection.style.display = 'none';
                }
            } catch (err) {
                console.error('Failed to load history', err);
            }
        }

        askBtn.addEventListener('click', async () => {
            const question = questionInput.value.trim();
            if (!question) return;

            // UI Reset
            resultCard.style.display = 'none';
            loader.style.display = 'flex';
            askBtn.disabled = true;

            try {
                const response = await fetch('/ask', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        question: question,
                        rewrite: rewriteCheckbox.checked
                    })
                });
                
                const data = await response.json();
                
                // Set status badge
                if (data.context_found) {
                    statusBadge.innerText = 'Context Found';
                    statusBadge.className = 'status-chip status-found';
                } else {
                    statusBadge.innerText = 'Refused / Not Found';
                    statusBadge.className = 'status-chip status-not-found';
                }

                resultAnswer.innerText = data.answer;
                
                // Build sources
                sourcesContainer.innerHTML = '';
                if (data.sources && data.sources.length > 0) {
                    data.sources.forEach(src => {
                        const chip = document.createElement('span');
                        chip.className = 'source-chip';
                        chip.innerText = src;
                        sourcesContainer.appendChild(chip);
                    });
                } else {
                    const noSources = document.createElement('span');
                    noSources.style.color = 'var(--text-muted)';
                    noSources.style.fontSize = '0.9rem';
                    noSources.innerText = 'None';
                    sourcesContainer.appendChild(noSources);
                }

                resultCard.style.display = 'block';
            } catch (err) {
                console.error(err);
                alert('Failed to get answer. Please check console.');
            } finally {
                loader.style.display = 'none';
                askBtn.disabled = false;
                loadHistory();
            }
        });

        // Initialize history load
        loadHistory();
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)