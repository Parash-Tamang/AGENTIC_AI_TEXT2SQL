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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from src.knowledgebase.controller.knowledgebase_controller import router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Knowledge Base API",
    description="Vector knowledge base management for database schemas and views",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(router)


# ── Exception Handlers ────────────────────────────────────────────────────────────


@app.exception_handler(HTTPException)
async def unified_exception_handler(request: Request, exc: HTTPException):
    """Unified exception handler for all HTTP errors.

    Wraps all errors in the standard {success, message, data} envelope.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail, "data": None},
    )


# ── Health Check ──────────────────────────────────────────────────────────────────


@app.get("/health", tags=["health"])
def health_check():
    """Health check endpoint."""
    return {"success": True, "message": "Knowledge Base API is running", "data": None}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
