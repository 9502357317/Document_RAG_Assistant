from fastapi import FastAPI
from app.api.routes import router
from contextlib import asynccontextmanager
from app.db import init_db
from app.logging_config import setup_logging

setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    
    # Auto-index corpus files on startup so the vector store is populated
    try:
        import logging
        from app.services.rag_service import rag_service, PROJECT_ROOT
        logger = logging.getLogger(__name__)
        
        corpus_dir = PROJECT_ROOT / "corpus" / "corpus"
        if not corpus_dir.exists():
            corpus_dir = PROJECT_ROOT / "corpus"
            
        if corpus_dir.exists():
            logger.info("Auto-indexing corpus files on startup...")
            indexed_count = 0
            for file_path in corpus_dir.glob("*"):
                if file_path.is_file():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        rag_service.index_document(file_path.name, content)
                        indexed_count += 1
                    except Exception as fe:
                        logger.error(f"Error indexing {file_path.name}: {fe}")
            logger.info(f"Auto-indexed {indexed_count} files. Total chunks: {rag_service.get_total_chunks()}")
        else:
            logger.warning("Corpus directory not found during auto-indexing.")
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Auto-indexing failed: {e}")
        
    yield

app = FastAPI(
    title="Address Extraction with LLM and Fallback",
    lifespan=lifespan
)

app.include_router(router)

from fastapi.responses import RedirectResponse

@app.get("/")
def home():
    return RedirectResponse(url="/ask")