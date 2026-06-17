import logging
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# Logger used for database startup and migration messages.
logger = logging.getLogger(__name__)

import os

# Store registry.db in the project root directory beside main.py.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if os.getenv("TESTING") == "1":
    DATABASE_PATH = PROJECT_ROOT / "test_registry.db"
else:
    DATABASE_PATH = PROJECT_ROOT / "registry.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

# Create the SQLAlchemy engine for SQLite.
# check_same_thread=False allows FastAPI requests to use database sessions
# from different worker threads.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Reusable SQLAlchemy session factory.
# expire_on_commit=False keeps ORM objects readable after commit.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


# Base class inherited by every SQLAlchemy ORM model.
class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create missing tables and run small SQLite migrations."""

    # Import models here so they are registered with Base.metadata.
    # This avoids circular imports while still allowing create_all().
    from app.models import database_models  # noqa: F401

    # Creates any missing tables, including upload_events.
    # Existing tables are not modified by create_all().
    Base.metadata.create_all(bind=engine)

    # Repair older databases created before address_documents had an id column.
    _migrate_address_documents_id()

    # Add Task 5 schema pieces for existing registry.db files.
    _migrate_task5_schema()

    logger.info("Database initialized: %s", DATABASE_PATH)


def _migrate_address_documents_id() -> None:
    """
    Add the link-table surrogate ID for databases created before this schema.

    SQLite cannot add a primary-key column to an existing table, so the table
    is rebuilt and existing links are copied across.
    """

    inspector = inspect(engine)

    if "address_documents" not in inspector.get_table_names():
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("address_documents")
    }

    if "id" in columns:
        return

    logger.info("Migrating address_documents table to include id column.")

    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))

        connection.execute(
            text(
                """
                CREATE TABLE address_documents_new (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    address_id INTEGER NOT NULL,
                    document_id INTEGER NOT NULL,
                    CONSTRAINT uq_address_documents_address_document
                        UNIQUE (address_id, document_id),
                    FOREIGN KEY(address_id)
                        REFERENCES addresses (id) ON DELETE CASCADE,
                    FOREIGN KEY(document_id)
                        REFERENCES documents (id) ON DELETE CASCADE
                )
                """
            )
        )

        connection.execute(
            text(
                """
                INSERT OR IGNORE INTO address_documents_new (
                    address_id,
                    document_id
                )
                SELECT address_id, document_id
                FROM address_documents
                """
            )
        )

        connection.execute(text("DROP TABLE address_documents"))

        connection.execute(
            text(
                "ALTER TABLE address_documents_new "
                "RENAME TO address_documents"
            )
        )

        connection.execute(text("PRAGMA foreign_keys=ON"))


def _migrate_task5_schema() -> None:
    """
    Add Task 5 database changes to an existing SQLite database.

    SQLAlchemy create_all() creates missing tables, but it does not add new
    columns or indexes to tables that already exist. These checks keep the
    migration safe to run every time the backend starts.
    """

    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    if "documents" not in table_names:
        return

    document_columns = {
        column["name"]
        for column in inspector.get_columns("documents")
    }

    with engine.begin() as connection:
        # Stores how many extracted addresses reused existing normalized rows.
        if "duplicate_addresses_caught" not in document_columns:
            logger.info(
                "Adding documents.duplicate_addresses_caught column."
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE documents
                    ADD COLUMN duplicate_addresses_caught
                    INTEGER NOT NULL DEFAULT 0
                    """
                )
            )

        # Speeds up dedupe lookup:
        # SELECT * FROM addresses WHERE normalized = :normalized
        if "addresses" in table_names:
            logger.info("Ensuring addresses.normalized index exists.")
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_addresses_normalized
                    ON addresses(normalized)
                    """
                )
            )

        if "content_hash" not in document_columns:
            logger.info("Adding documents.content_hash column.")
            connection.execute(
                text(
                    """
                    ALTER TABLE documents
                    ADD COLUMN content_hash
                    VARCHAR(64) NULL
                    """
                )
            )
            logger.info("Ensuring documents.content_hash index exists.")
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_documents_content_hash
                    ON documents(content_hash)
                    """
                )
            )

        # Create FTS5 virtual table and sync triggers
        if "addresses_fts" not in table_names:
            logger.info("Creating addresses_fts virtual table for FTS5.")
            connection.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE addresses_fts USING fts5(
                        address_id UNINDEXED,
                        raw_text
                    )
                    """
                )
            )
            logger.info("Populating addresses_fts with existing addresses.")
            connection.execute(
                text(
                    """
                    INSERT INTO addresses_fts (address_id, raw_text)
                    SELECT id, raw_text FROM addresses
                    """
                )
            )
            logger.info("Creating FTS5 sync triggers.")
            connection.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS trg_addresses_insert AFTER INSERT ON addresses
                    BEGIN
                        INSERT INTO addresses_fts(address_id, raw_text) VALUES (new.id, new.raw_text);
                    END;
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS trg_addresses_update AFTER UPDATE ON addresses
                    BEGIN
                        UPDATE addresses_fts SET raw_text = new.raw_text WHERE address_id = old.id;
                    END;
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS trg_addresses_delete AFTER DELETE ON addresses
                    BEGIN
                        DELETE FROM addresses_fts WHERE address_id = old.id;
                    END;
                    """
                )
            )


def get_db():
    """Provide a database session and close it after use."""

    session = SessionLocal()

    try:
        yield session
    finally:
        session.close()


def insert_record(record):
    """Insert one ORM record and return it with its generated ID."""

    with SessionLocal() as session:
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def get_all(model):
    """Return all records for the supplied ORM model."""

    with SessionLocal() as session:
        statement = select(model)
        return list(session.scalars(statement).all())


def get_by_id(model, record_id: int):
    """Return one record by primary-key ID, or None if it does not exist."""

    with SessionLocal() as session:
        return session.get(model, record_id)


def link_address_to_document(address_id: int, document_id: int):
    """Create a link between an address and a document."""

    # Import here to avoid circular imports during module initialization.
    from app.models.database_models import AddressDocument

    link = AddressDocument(
        address_id=address_id,
        document_id=document_id,
    )

    return insert_record(link)


# Initialize the database when this module is run directly.
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    init_db()