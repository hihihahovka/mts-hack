"""
RAG Files Router — dedicated FastAPI endpoints for file-based RAG.

Endpoints:
  POST /upload            — upload a file, extract text, embed, store
  POST /query             — query a collection by question
  POST /upload-and-query  — upload + query in one call
  GET  /health            — check embedding service health
  GET  /collections/{name}/exists — check if collection exists
"""

import logging
import os
import uuid


import requests
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional

from open_webui.retrieval.rag_files.pipeline import (
    process_and_store,
    query_rag,
)
from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
from open_webui.utils.auth import get_verified_user
from open_webui.config import UPLOAD_DIR

log = logging.getLogger(__name__)

router = APIRouter()

# Supported file extensions
SUPPORTED_EXTENSIONS = {"pdf", "docx", "txt"}

# MIME type mapping
MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}


# ──────────────────────────────────────────────
#  Request/Response models
# ──────────────────────────────────────────────

class QueryRequest(BaseModel):
    collection_name: str
    question: str
    k: int = 5


class QueryResponse(BaseModel):
    question: str
    collection_name: str
    results_count: int
    chunks: list


class UploadResponse(BaseModel):
    status: bool
    collection_name: str
    filename: str
    chunk_count: int
    text_length: int
    text_preview: str


class UploadAndQueryRequest(BaseModel):
    question: str
    k: int = 5


class HealthResponse(BaseModel):
    status: str
    embedding_engine: str
    embedding_model: str
    embedding_api_url: str
    embedding_reachable: bool


# ──────────────────────────────────────────────
#  POST /upload
# ──────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    collection_name: Optional[str] = Form(None),
    chunk_size: int = Form(1500),
    chunk_overlap: int = Form(100),
    user=Depends(get_verified_user),
):
    """
    Upload a PDF, DOCX, or TXT file for RAG processing.

    The file is extracted, chunked, embedded (bge-m3), and stored
    in the vector database (ChromaDB).
    """
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '.{ext}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    # Save uploaded file to a temporary location
    file_id = uuid.uuid4().hex[:12]
    temp_dir = os.path.join(UPLOAD_DIR, "rag_temp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{file_id}_{filename}")

    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        content_type = file.content_type or MIME_TYPES.get(ext, "application/octet-stream")

        # Process in a thread to avoid blocking the event loop
        result = await run_in_threadpool(
            process_and_store,
            request,
            temp_path,
            filename,
            content_type,
            collection_name=collection_name,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            overwrite=True,
            user=user,
        )

        return UploadResponse(
            status=True,
            collection_name=result["collection_name"],
            filename=filename,
            chunk_count=result["chunk_count"],
            text_length=result["text_length"],
            text_preview=result["text_preview"],
        )

    except Exception as e:
        log.exception(f"Error processing file '{filename}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing file: {str(e)}",
        )
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ──────────────────────────────────────────────
#  POST /query
# ──────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse)
async def query_collection_endpoint(
    request: Request,
    form_data: QueryRequest,
    user=Depends(get_verified_user),
):
    """
    Query an indexed collection with a natural language question.

    Returns the top-k most relevant chunks.
    """
    if not VECTOR_DB_CLIENT.has_collection(collection_name=form_data.collection_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{form_data.collection_name}' not found. Upload a file first.",
        )

    try:
        result = await query_rag(
            request,
            collection_name=form_data.collection_name,
            question=form_data.question,
            k=form_data.k,
        )
        return QueryResponse(**result)

    except Exception as e:
        log.exception(f"Error querying collection '{form_data.collection_name}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error querying: {str(e)}",
        )


# ──────────────────────────────────────────────
#  POST /upload-and-query
# ──────────────────────────────────────────────

@router.post("/upload-and-query")
async def upload_and_query(
    request: Request,
    file: UploadFile = File(...),
    question: str = Form(...),
    k: int = Form(5),
    chunk_size: int = Form(1500),
    chunk_overlap: int = Form(100),
    user=Depends(get_verified_user),
):
    """
    Upload a file AND query it in one request.

    This is a convenience endpoint for end-to-end RAG testing:
    1. Upload file → extract → chunk → embed → store
    2. Query the stored embeddings with the given question
    3. Return both the upload result and the retrieved chunks
    """
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '.{ext}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    file_id = uuid.uuid4().hex[:12]
    temp_dir = os.path.join(UPLOAD_DIR, "rag_temp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{file_id}_{filename}")

    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        content_type = file.content_type or MIME_TYPES.get(ext, "application/octet-stream")

        # Step 1: Process and store
        upload_result = await run_in_threadpool(
            process_and_store,
            request,
            temp_path,
            filename,
            content_type,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            overwrite=True,
            user=user,
        )

        # Step 2: Query
        query_result = await query_rag(
            request,
            collection_name=upload_result["collection_name"],
            question=question,
            k=k,
        )

        return {
            "status": True,
            "upload": upload_result,
            "query": query_result,
        }

    except Exception as e:
        log.exception(f"Error in upload-and-query for '{filename}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error: {str(e)}",
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ──────────────────────────────────────────────
#  GET /health
# ──────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """
    Check the health of the RAG system.

    Verifies that the embedding service (bge-m3) is reachable.
    """
    engine = request.app.state.config.RAG_EMBEDDING_ENGINE
    model = request.app.state.config.RAG_EMBEDDING_MODEL

    if engine == "openai":
        api_url = request.app.state.config.RAG_OPENAI_API_BASE_URL
        api_key = request.app.state.config.RAG_OPENAI_API_KEY
    elif engine == "ollama":
        api_url = request.app.state.config.RAG_OLLAMA_BASE_URL
        api_key = request.app.state.config.RAG_OLLAMA_API_KEY
    else:
        api_url = "local"
        api_key = ""

    # Try to reach the embedding API
    reachable = False
    if api_url and api_url != "local":
        try:
            r = requests.get(
                f"{api_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5,
            )
            reachable = r.status_code == 200
        except Exception:
            reachable = False
    else:
        # Local embedding model — check if ef is loaded
        reachable = request.app.state.ef is not None

    return HealthResponse(
        status="ok" if reachable else "degraded",
        embedding_engine=engine,
        embedding_model=model,
        embedding_api_url=api_url or "local",
        embedding_reachable=reachable,
    )


# ──────────────────────────────────────────────
#  GET /collections/{name}/exists
# ──────────────────────────────────────────────

@router.get("/collections/{name}/exists")
async def check_collection_exists(
    name: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """
    Check if a specific RAG collection exists in the vector database.
    """
    try:
        exists = VECTOR_DB_CLIENT.has_collection(collection_name=name)
        return {
            "collection_name": name,
            "exists": exists,
        }
    except Exception as e:
        log.exception(f"Error checking collection '{name}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error checking collection: {str(e)}",
        )
