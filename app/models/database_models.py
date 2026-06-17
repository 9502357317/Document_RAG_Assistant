from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Float,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Unique SHA-256 prevents storing the same file bytes twice.
    sha256: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # processed / failed

    failure_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    doc_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    # Counts how many extracted addresses reused an existing normalized row.
    duplicate_addresses_caught: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # Stores the SHA-256 hash of the lowercased, whitespace-collapsed extracted text.
    content_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    raw_text: Mapped[str | None] = mapped_column(
        String(100000),
        nullable=True,
    )

    extraction_path: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    address_links = relationship(
        "AddressDocument",
        back_populates="document",
    )


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    raw_text: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )

    # Indexed because deduplication looks up addresses by normalized value.
    normalized: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        index=True,
    )

    street: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    city: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    state: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    zip: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    review_status: Mapped[str] = mapped_column(
        String(50),
        default="unreviewed",
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    document_links = relationship(
        "AddressDocument",
        back_populates="address",
    )


class AddressDocument(Base):
    __tablename__ = "address_documents"

    # Prevents the same address/document link from being inserted twice.
    __table_args__ = (
        UniqueConstraint(
            "address_id",
            "document_id",
            name="uq_address_documents_address_document",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    address_id: Mapped[int] = mapped_column(
        ForeignKey("addresses.id", ondelete="CASCADE"),
        nullable=False,
    )

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    address = relationship(
        "Address",
        back_populates="document_links",
    )

    document = relationship(
        "Document",
        back_populates="address_links",
    )


class UploadEvent(Base):
    __tablename__ = "upload_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # Example: duplicate_file_rejected
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # For duplicate files, this points to the original document id.
    document_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        UniqueConstraint(
            "address_a_id",
            "address_b_id",
            name="uq_duplicate_candidates_pair",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    address_a_id: Mapped[int] = mapped_column(
        ForeignKey("addresses.id", ondelete="CASCADE"),
        nullable=False,
    )

    address_b_id: Mapped[int] = mapped_column(
        ForeignKey("addresses.id", ondelete="CASCADE"),
        nullable=False,
    )

    score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    address_a = relationship(
        "Address",
        foreign_keys=[address_a_id],
    )
    address_b = relationship(
        "Address",
        foreign_keys=[address_b_id],
    )


class RagLog(Base):
    __tablename__ = "rag_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    question: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )
    answer: Mapped[str] = mapped_column(
        String(10000),
        nullable=False,
    )
    sources: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )
    latency_ms: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )