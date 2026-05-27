"""
main.py
───────
FastAPI application entry point for the Knowledge Base API.

Run with:
    uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

Then visit:
    - Swagger UI:  http://localhost:8000/docs
    - ReDoc:       http://localhost:8000/redoc
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import logging

from src.knowledgebase.controller.knowledgebase_controller import router as kb_router
from src.agent.controller.chat_controller import router as chat_router
from src.knowledgebase.config.graph_setting import graph_manager  # ✅ import singleton
from src.agent.observability import configure_workflow_logging

configure_workflow_logging()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("app")


# ── Lifespan ──────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):

    # ── Startup ───────────────────────────────────────────────
    log.info("API starting up...")
    try:
        graph_manager.load_all()  # ✅ loads all graphs into memory
    except Exception as e:
        log.error(f"Graph load failed: {e}")

    yield

    # ── Shutdown ──────────────────────────────────────────────
    log.info("API shutting down...")


# ── App ───────────────────────────────────────────────────────

app = FastAPI(title="Knowledge Base API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(kb_router)
app.include_router(chat_router)

# Serve assets (charts/images) as static files at /assets/*
app.mount("/assets", StaticFiles(directory="assets"), name="assets")


# ── Exception Handlers ────────────────────────────────────────


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail, "data": None},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "Internal server error", "data": None},
    )


# ── Health ────────────────────────────────────────────────────


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "success": True,
        "message": "API is running",
        "data": None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
