from datetime import datetime
import hashlib
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select, or_, delete, text
from sqlalchemy.orm import selectinload

from app.db import SessionLocal
from app.models.database_models import (
    Address as AddressRecord,
    AddressDocument,
    Document,
    UploadEvent,
    DuplicateCandidate,
    RagLog,
)
from app.services.address_normalizer import normalize_address, clean_address, abbreviate_address


class DatabaseService:
    @staticmethod
    def get_file_details(file: UploadFile) -> dict:
        """Read file metadata and calculate its SHA-256 hash."""

        # Read uploaded bytes for hashing.
        # Then reset the stream so extraction can read the file again.
        file.file.seek(0)
        content = file.file.read()
        file.file.seek(0)

        filename = file.filename or "unknown"
        extension = Path(filename).suffix.lower().lstrip(".")

        return {
            "filename": filename,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "doc_type": extension or None,
        }

    @staticmethod
    def get_document_by_sha256(sha256: str):
        """Find an existing document using its SHA-256 hash."""

        with SessionLocal() as session:
            return session.scalar(
                select(Document).where(Document.sha256 == sha256)
            )

    @staticmethod
    def get_document_by_content_hash(content_hash: str):
        """Find an existing successfully processed document using its content hash."""

        with SessionLocal() as session:
            return session.scalar(
                select(Document).where(
                    Document.content_hash == content_hash,
                    Document.status == "processed",
                )
            )

    @staticmethod
    def record_duplicate_file_rejected(
        file_details: dict,
        existing_document_id: int,
    ) -> None:
        """
        Record a rejected duplicate file upload.

        Duplicate files do not create new document rows, so this event table
        lets /stats count how many duplicate uploads were rejected.
        """

        with SessionLocal() as session:
            session.add(
                UploadEvent(
                    event_type="duplicate_file_rejected",
                    document_id=existing_document_id,
                    filename=file_details["filename"],
                    sha256=file_details["sha256"],
                )
            )
            session.commit()

    @staticmethod
    def create_document(file_details: dict) -> int:
        """
        Create a document before extraction starts.

        The temporary failed state ensures an interrupted extraction still
        leaves a database record showing that the upload was received.
        """

        with SessionLocal() as session:
            document = Document(
                **file_details,
                status="failed",
                failure_reason="Extraction did not complete.",
                duplicate_addresses_caught=0,
            )

            session.add(document)
            session.commit()
            session.refresh(document)

            return document.id

    @staticmethod
    def save_extracted_addresses(
        document_id: int,
        extracted_addresses: list,
        content_hash: str | None = None,
        raw_text: str | None = None,
        extraction_path: str | None = None,
    ) -> list[dict]:
        """
        Save extracted addresses using normalized-address deduplication.

        If an address with the same normalized string already exists, reuse it
        and only create a new address_documents link. If it is new, insert it.
        """

        address_results = []
        duplicate_addresses_caught = 0
        seen_links = set()

        with SessionLocal() as session:
            document = session.get(Document, document_id)

            if document is None:
                raise ValueError("Document not found.")

            if raw_text is not None:
                document.raw_text = raw_text
            if extraction_path is not None:
                document.extraction_path = extraction_path

            for extracted in extracted_addresses:
                # Normalize and parse the raw address.
                # The normalized value is the dedupe key.
                normalized_data = normalize_address(extracted.input_text)
                normalized = normalized_data["normalized"]

                existing_address = None

                # Use the indexed normalized column for fast dedupe lookup.
                if normalized:
                    existing_address = session.scalar(
                        select(AddressRecord).where(
                            AddressRecord.normalized == normalized
                        )
                    )

                if existing_address:
                    address = existing_address
                    is_new = False
                    duplicate_addresses_caught += 1
                else:
                    address = AddressRecord(
                        raw_text=extracted.input_text,
                        normalized=normalized,
                        street=normalized_data["street"],
                        city=normalized_data["city"],
                        state=normalized_data["state"],
                        zip=normalized_data["zip"],
                        review_status=normalized_data["review_status"],
                    )

                    # Flush assigns the generated address ID before commit.
                    session.add(address)
                    session.flush()
                    is_new = True

                    # -------------------------------------------------------------
                    # Near-Duplicate Fuzzy Matching (Pairwise Comparison)
                    # -------------------------------------------------------------
                    # To prevent performance bottleneck (O(N^2) complexity explosion),
                    # we do not compare the new address against the entire database.
                    # Instead, we only fetch plausible candidates that share the
                    # same city or ZIP code.
                    from rapidfuzz import fuzz

                    # Determine comparison filter conditions based on non-null values
                    or_conditions = []
                    if address.city:
                        or_conditions.append(AddressRecord.city == address.city)
                    if address.zip:
                        or_conditions.append(AddressRecord.zip == address.zip)

                    if or_conditions:
                        # Fetch all existing active (non-deleted) addresses that match city/zip
                        candidates_stmt = (
                            select(AddressRecord)
                            .where(
                                AddressRecord.id != address.id,
                                AddressRecord.deleted_at.is_(None),
                                or_(*or_conditions)
                            )
                        )
                        matching_candidates = session.scalars(candidates_stmt).all()
                    else:
                        matching_candidates = []

                    for candidate in matching_candidates:
                        # Skip if either address is missing a normalized string
                        if not address.normalized or not candidate.normalized:
                            continue

                        # Compare the normalized strings pairwise using Levenshtein-based similarity
                        score = fuzz.ratio(address.normalized, candidate.normalized)

                        # Store pairs scoring at or above the threshold (90)
                        if score >= 90:
                            # Order the IDs so that address_a_id is always the smaller value.
                            # This maintains consistency in unique candidate rows.
                            addr_a_id, addr_b_id = sorted([address.id, candidate.id])

                            # Check if the duplicate pair is already registered to avoid duplicates
                            existing_pair = session.scalar(
                                select(DuplicateCandidate).where(
                                    DuplicateCandidate.address_a_id == addr_a_id,
                                    DuplicateCandidate.address_b_id == addr_b_id,
                                )
                            )

                            if existing_pair is None:
                                session.add(
                                    DuplicateCandidate(
                                        address_a_id=addr_a_id,
                                        address_b_id=addr_b_id,
                                        score=score,
                                        status="pending"
                                    )
                                )

                # Avoid inserting the same address/document link twice.
                link_key = (address.id, document_id)
                if link_key not in seen_links:
                    existing_link = session.scalar(
                        select(AddressDocument).where(
                            AddressDocument.address_id == address.id,
                            AddressDocument.document_id == document_id,
                        )
                    )

                    if existing_link is None:
                        session.add(
                            AddressDocument(
                                address_id=address.id,
                                document_id=document_id,
                            )
                        )
                    seen_links.add(link_key)

                address_results.append(
                    {
                        "id": address.id,
                        "is_new": is_new,
                    }
                )

            # Mark the document successful only after every address/link is saved.
            document.status = "processed"
            document.failure_reason = None
            document.duplicate_addresses_caught = duplicate_addresses_caught
            if content_hash:
                document.content_hash = content_hash
            session.commit()

        return address_results

    @staticmethod
    def mark_document_failed(document_id: int, reason: str) -> None:
        """Mark a document as failed and save a readable failure reason."""

        with SessionLocal() as session:
            document = session.get(Document, document_id)

            if document is None:
                return

            document.status = "failed"

            # Match the maximum length of the failure_reason database column.
            document.failure_reason = reason[:500]
            session.commit()

    @staticmethod
    def list_documents(status: str | None = None) -> list[dict]:
        """List documents, optionally filtered by processing status."""

        with SessionLocal() as session:
            statement = select(Document).order_by(
                Document.uploaded_at.desc()
            )

            if status:
                statement = statement.where(Document.status == status)

            documents = session.scalars(statement).all()

            return [
                {
                    "id": document.id,
                    "filename": document.filename,
                    "size_bytes": document.size_bytes,
                    "sha256": document.sha256,
                    "status": document.status,
                    "failure_reason": document.failure_reason,
                    "doc_type": document.doc_type,
                    "uploaded_at": document.uploaded_at.isoformat(),
                    "duplicate_addresses_caught": (
                        document.duplicate_addresses_caught
                    ),
                    "raw_text": document.raw_text,
                    "extraction_path": document.extraction_path,
                }
                for document in documents
            ]

    @staticmethod
    def get_document(document_id: int) -> dict | None:
        """Return document metadata and all linked normalized addresses."""

        with SessionLocal() as session:
            # Eagerly load address links and their address records.
            statement = (
                select(Document)
                .options(
                    selectinload(Document.address_links).selectinload(
                        AddressDocument.address
                    )
                )
                .where(Document.id == document_id)
            )

            document = session.scalar(statement)

            if document is None:
                return None

            return {
                "id": document.id,
                "filename": document.filename,
                "size_bytes": document.size_bytes,
                "sha256": document.sha256,
                "status": document.status,
                "failure_reason": document.failure_reason,
                "doc_type": document.doc_type,
                "uploaded_at": document.uploaded_at.isoformat(),
                "duplicate_addresses_caught": (
                    document.duplicate_addresses_caught
                ),
                "raw_text": document.raw_text,
                "extraction_path": document.extraction_path,
                "addresses": [
                    {
                        "id": link.address.id,
                        "raw_text": link.address.raw_text,
                        "normalized": link.address.normalized,
                        "street": link.address.street,
                        "city": link.address.city,
                        "state": link.address.state,
                        "zip": link.address.zip,
                        "review_status": link.address.review_status,
                    }
                    for link in document.address_links
                ],
            }

    @staticmethod
    def list_addresses(
        limit: int = 20,
        offset: int = 0,
        search: str | None = None,
        city: str | None = None,
        state: str | None = None,
        zip: str | None = None,
    ) -> dict:
        """
        Return one paginated page of active addresses.

        Soft-deleted rows are excluded by default because deleted_at must be
        NULL for an address to appear in normal registry browsing.
        Optional filters are combined together and SQLAlchemy parameterizes
        values so user input is never interpolated into raw SQL.
        """

        with SessionLocal() as session:
            filters = [
                AddressRecord.deleted_at.is_(None),
                or_(AddressRecord.review_status != "merged", AddressRecord.review_status.is_(None))
            ]

            if search:
                words = [w.strip() for w in search.strip().split() if w.strip()]
                if words:
                    # Escape quotes and prefix-match each word in FTS5 index
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

            total = session.scalar(
                select(func.count(AddressRecord.id)).where(*filters)
            ) or 0

            statement = (
                select(AddressRecord)
                .where(*filters)
                .order_by(AddressRecord.created_at.desc())
                .limit(limit)
                .offset(offset)
            )

            addresses = session.scalars(statement).all()

            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "filters": {
                    "search": search,
                    "city": city,
                    "state": state,
                    "zip": zip,
                },
                "items": [
                    {
                        "id": address.id,
                        "raw_text": address.raw_text,
                        "normalized": address.normalized,
                        "street": address.street,
                        "city": address.city,
                        "state": address.state,
                        "zip": address.zip,
                        "review_status": address.review_status,
                        "created_at": address.created_at.isoformat(),
                    }
                    for address in addresses
                ],
            }

    @staticmethod
    def get_filter_options() -> dict:
        """Return unique cities, states, and ZIP codes from active addresses for filters."""
        with SessionLocal() as session:
            cities_stmt = (
                select(AddressRecord.city)
                .where(
                    AddressRecord.deleted_at.is_(None),
                    AddressRecord.city.is_not(None),
                    or_(AddressRecord.review_status != "merged", AddressRecord.review_status.is_(None)),
                )
                .distinct()
                .order_by(AddressRecord.city)
            )
            states_stmt = (
                select(AddressRecord.state)
                .where(
                    AddressRecord.deleted_at.is_(None),
                    AddressRecord.state.is_not(None),
                    or_(AddressRecord.review_status != "merged", AddressRecord.review_status.is_(None)),
                )
                .distinct()
                .order_by(AddressRecord.state)
            )
            zips_stmt = (
                select(AddressRecord.zip)
                .where(
                    AddressRecord.deleted_at.is_(None),
                    AddressRecord.zip.is_not(None),
                    or_(AddressRecord.review_status != "merged", AddressRecord.review_status.is_(None)),
                )
                .distinct()
                .order_by(AddressRecord.zip)
            )

            cities = session.scalars(cities_stmt).all()
            states = session.scalars(states_stmt).all()
            zips = session.scalars(zips_stmt).all()

            return {
                "cities": [c for c in cities if c and c.strip()],
                "states": [s for s in states if s and s.strip()],
                "zips": [z for z in zips if z and z.strip()],
            }

    @staticmethod
    def get_address(address_id: int) -> dict | None:
        """
        Return one address plus every document where it appeared.

        This keeps the registry useful for audit/review because the user can
        see which source uploads produced the address.
        """

        with SessionLocal() as session:
            statement = (
                select(AddressRecord)
                .options(
                    selectinload(AddressRecord.document_links).selectinload(
                        AddressDocument.document
                    )
                )
                .where(AddressRecord.id == address_id)
            )

            address = session.scalar(statement)

            if address is None:
                return None

            return {
                "id": address.id,
                "raw_text": address.raw_text,
                "normalized": address.normalized,
                "street": address.street,
                "city": address.city,
                "state": address.state,
                "zip": address.zip,
                "review_status": address.review_status,
                "deleted_at": (
                    address.deleted_at.isoformat()
                    if address.deleted_at
                    else None
                ),
                "created_at": address.created_at.isoformat(),
                "documents": [
                    {
                        "id": link.document.id,
                        "filename": link.document.filename,
                        "size_bytes": link.document.size_bytes,
                        "status": link.document.status,
                        "failure_reason": link.document.failure_reason,
                        "doc_type": link.document.doc_type,
                        "uploaded_at": link.document.uploaded_at.isoformat(),
                    }
                    for link in address.document_links
                ],
            }

    @staticmethod
    def soft_delete_address(address_id: int) -> bool:
        """
        Soft-delete one address by setting deleted_at.

        The row stays in the database, and address_documents links stay intact,
        but normal address lists will hide it.
        """

        with SessionLocal() as session:
            address = session.get(AddressRecord, address_id)

            if address is None:
                return False

            if address.deleted_at is None:
                address.deleted_at = datetime.utcnow()
                session.commit()

            return True

    @staticmethod
    def get_stats() -> dict:
        """Return task 5 summary counts."""

        with SessionLocal() as session:
            total_documents = session.scalar(
                select(func.count(Document.id))
            ) or 0

            unique_addresses = session.scalar(
                select(func.count(AddressRecord.id)).where(
                    AddressRecord.deleted_at.is_(None),
                    or_(AddressRecord.review_status != "merged", AddressRecord.review_status.is_(None))
                )
            ) or 0

            duplicate_files_rejected = session.scalar(
                select(func.count(UploadEvent.id)).where(
                    UploadEvent.event_type == "duplicate_file_rejected"
                )
            ) or 0

            duplicate_addresses_caught = session.scalar(
                select(
                    func.coalesce(
                        func.sum(Document.duplicate_addresses_caught),
                        0,
                    )
                )
            ) or 0

            return {
                "total_documents": total_documents,
                "unique_addresses": unique_addresses,
                "duplicate_files_rejected": duplicate_files_rejected,
                "duplicate_addresses_caught": duplicate_addresses_caught,
            }

    @staticmethod
    def patch_address(address_id: int, data: dict) -> dict | None:
        """Update specific fields of an address and re-derive its normalized string."""
        with SessionLocal() as session:
            address = session.get(AddressRecord, address_id)
            if address is None:
                return None

            for field in ["street", "city", "state", "zip", "review_status"]:
                if field in data:
                    val = data[field]
                    if val is not None and field != "review_status":
                        val = val.strip().upper()
                    setattr(address, field, val)

            # Re-derive normalized address string
            parts = [address.street, address.city, address.state, address.zip]
            combined = " ".join([p for p in parts if p])
            address.normalized = abbreviate_address(clean_address(combined))

            session.commit()
            session.refresh(address)

            return {
                "id": address.id,
                "raw_text": address.raw_text,
                "normalized": address.normalized,
                "street": address.street,
                "city": address.city,
                "state": address.state,
                "zip": address.zip,
                "review_status": address.review_status,
                "created_at": address.created_at.isoformat(),
            }

    @staticmethod
    def list_duplicates() -> list[dict]:
        """List all pending duplicate candidates that involve active (non-deleted, non-merged) addresses."""
        with SessionLocal() as session:
            from sqlalchemy.orm import aliased
            AddrA = aliased(AddressRecord)
            AddrB = aliased(AddressRecord)

            statement = (
                select(DuplicateCandidate)
                .join(AddrA, DuplicateCandidate.address_a_id == AddrA.id)
                .join(AddrB, DuplicateCandidate.address_b_id == AddrB.id)
                .where(
                    DuplicateCandidate.status == "pending",
                    AddrA.deleted_at.is_(None),
                    AddrB.deleted_at.is_(None),
                    or_(AddrA.review_status != "merged", AddrA.review_status.is_(None)),
                    or_(AddrB.review_status != "merged", AddrB.review_status.is_(None))
                )
                .order_by(DuplicateCandidate.score.desc())
            )
            candidates = session.scalars(statement).all()
            return [
                {
                    "id": cand.id,
                    "score": cand.score,
                    "status": cand.status,
                    "created_at": cand.created_at.isoformat(),
                    "address_a": {
                        "id": cand.address_a.id,
                        "raw_text": cand.address_a.raw_text,
                        "normalized": cand.address_a.normalized,
                        "street": cand.address_a.street,
                        "city": cand.address_a.city,
                        "state": cand.address_a.state,
                        "zip": cand.address_a.zip,
                        "review_status": cand.address_a.review_status,
                    } if cand.address_a else None,
                    "address_b": {
                        "id": cand.address_b.id,
                        "raw_text": cand.address_b.raw_text,
                        "normalized": cand.address_b.normalized,
                        "street": cand.address_b.street,
                        "city": cand.address_b.city,
                        "state": cand.address_b.state,
                        "zip": cand.address_b.zip,
                        "review_status": cand.address_b.review_status,
                    } if cand.address_b else None,
                }
                for cand in candidates
            ]

    @staticmethod
    def resolve_duplicate(duplicate_id: int, action: str, winning_address_id: int | None = None) -> bool:
        """Resolve a duplicate candidate pair by merging or dismissing."""
        with SessionLocal() as session:
            candidate = session.get(DuplicateCandidate, duplicate_id)
            if candidate is None or candidate.status != "pending":
                return False

            if action == "not_duplicate":
                session.delete(candidate)
                session.commit()
                return True

            if action == "merge":
                if not winning_address_id:
                    return False
                
                if winning_address_id not in (candidate.address_a_id, candidate.address_b_id):
                    return False

                winner_id = winning_address_id
                loser_id = candidate.address_b_id if winner_id == candidate.address_a_id else candidate.address_a_id

                winner = session.get(AddressRecord, winner_id)
                loser = session.get(AddressRecord, loser_id)
                if not winner or not loser:
                    return False

                # Set statuses
                winner.review_status = "verified"
                loser.review_status = "merged"

                # Repoint document links of loser to winner
                loser_links = session.scalars(
                    select(AddressDocument).where(AddressDocument.address_id == loser_id)
                ).all()

                for link in loser_links:
                    # Check if winner already linked to this document
                    exists = session.scalar(
                        select(AddressDocument).where(
                            AddressDocument.address_id == winner_id,
                            AddressDocument.document_id == link.document_id
                        )
                    )
                    if exists:
                        session.delete(link)
                    else:
                        link.address_id = winner_id

                # Cascade cleanup: remove all duplicate candidates involving the losing address
                session.execute(
                    delete(DuplicateCandidate).where(
                        or_(
                            DuplicateCandidate.address_a_id == loser_id,
                            DuplicateCandidate.address_b_id == loser_id
                        )
                    )
                )

                session.commit()
                return True

            return False

    @staticmethod
    def list_rag_logs(limit: int = 10) -> list[dict]:
        """Return the most recent RAG Q&A logs."""
        import json
        with SessionLocal() as session:
            statement = (
                select(RagLog)
                .order_by(RagLog.created_at.desc())
                .limit(limit)
            )
            logs = session.scalars(statement).all()
            return [
                {
                    "id": log.id,
                    "question": log.question,
                    "answer": log.answer,
                    "sources": json.loads(log.sources) if log.sources else [],
                    "latency_ms": log.latency_ms,
                    "created_at": log.created_at.isoformat()
                }
                for log in logs
            ]