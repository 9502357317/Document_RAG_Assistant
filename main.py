from fastapi import FastAPI
from app.api.routes import router
from contextlib import asynccontextmanager
from app.db import init_db
from app.logging_config import setup_logging

setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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