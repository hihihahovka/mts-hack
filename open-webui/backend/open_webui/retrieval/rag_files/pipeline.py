"""
RAG Pipeline — core logic for file-based Retrieval-Augmented Generation.

Wraps the existing Open WebUI infrastructure:
  Loader → chunking → embedding (bge-m3) → ChromaDB → retrieval

All heavy lifting is delegated to the existing codebase; this module
provides a clean, testable interface.
"""

import logging
import uuid
from typing import Optional

import ftfy
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from open_webui.retrieval.loaders.main import Loader
from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
from open_webui.retrieval.vector.utils import filter_metadata
from open_webui.retrieval.utils import (
    get_embedding_function,
    query_collection,
)
from open_webui.utils.misc import calculate_sha256_string, sanitize_text_for_db
from open_webui.config import (
    RAG_EMBEDDING_CONTENT_PREFIX,
    RAG_EMBEDDING_QUERY_PREFIX,
)
from open_webui.env import RAG_EMBEDDING_TIMEOUT

import asyncio

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  1. Text extraction
# ──────────────────────────────────────────────

def extract_text(
    file_path: str,
    filename: str,
    content_type: str,
    engine: str = "",
    **loader_kwargs,
) -> list[Document]:
    """
    Extract text from a file using the existing Open WebUI Loader.

    Supports: PDF, DOCX, TXT (and everything else the Loader supports).
    Returns a list of LangChain Documents.
    """
    loader = Loader(engine=engine, **loader_kwargs)
    docs = loader.load(filename, content_type, file_path)
    # Fix encoding issues
    docs = [
        Document(
            page_content=ftfy.fix_text(doc.page_content),
            metadata=doc.metadata,
        )
        for doc in docs
    ]
    log.info(f"Extracted {len(docs)} document(s) from '{filename}'")
    return docs


# ──────────────────────────────────────────────
#  2. Chunking
# ──────────────────────────────────────────────

def chunk_documents(
    docs: list[Document],
    chunk_size: int = 1500,
    chunk_overlap: int = 100,
) -> list[Document]:
    """
    Split documents into chunks using RecursiveCharacterTextSplitter.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )
    chunks = splitter.split_documents(docs)
    log.info(f"Split into {len(chunks)} chunk(s) (size={chunk_size}, overlap={chunk_overlap})")
    return chunks


# ──────────────────────────────────────────────
#  3. Embed + store
# ──────────────────────────────────────────────

def embed_and_store(
    request,
    chunks: list[Document],
    collection_name: str,
    metadata: Optional[dict] = None,
    overwrite: bool = False,
    user=None,
) -> bool:
    """
    Generate embeddings for chunks and store them in the vector database.

    Uses the embedding function configured on the application state
    (bge-m3 via MWS OpenAI-compatible API).
    """
    if not chunks:
        raise ValueError("No chunks to embed — document may be empty.")

    texts = [sanitize_text_for_db(chunk.page_content) for chunk in chunks]
    metadatas = [
        {
            **filter_metadata(chunk.metadata),
            **(metadata or {}),
            "embedding_config": {
                "engine": request.app.state.config.RAG_EMBEDDING_ENGINE,
                "model": request.app.state.config.RAG_EMBEDDING_MODEL,
            },
        }
        for chunk in chunks
    ]

    # Delete existing collection if overwrite
    if overwrite and VECTOR_DB_CLIENT.has_collection(collection_name=collection_name):
        VECTOR_DB_CLIENT.delete_collection(collection_name=collection_name)
        log.info(f"Deleted existing collection '{collection_name}' (overwrite=True)")

    # Build embedding function from app state
    embedding_function = get_embedding_function(
        request.app.state.config.RAG_EMBEDDING_ENGINE,
        request.app.state.config.RAG_EMBEDDING_MODEL,
        request.app.state.ef,
        (
            request.app.state.config.RAG_OPENAI_API_BASE_URL
            if request.app.state.config.RAG_EMBEDDING_ENGINE == "openai"
            else (
                request.app.state.config.RAG_OLLAMA_BASE_URL
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "ollama"
                else request.app.state.config.RAG_AZURE_OPENAI_BASE_URL
            )
        ),
        (
            request.app.state.config.RAG_OPENAI_API_KEY
            if request.app.state.config.RAG_EMBEDDING_ENGINE == "openai"
            else (
                request.app.state.config.RAG_OLLAMA_API_KEY
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "ollama"
                else request.app.state.config.RAG_AZURE_OPENAI_API_KEY
            )
        ),
        request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
        azure_api_version=(
            request.app.state.config.RAG_AZURE_OPENAI_API_VERSION
            if request.app.state.config.RAG_EMBEDDING_ENGINE == "azure_openai"
            else None
        ),
        enable_async=request.app.state.config.ENABLE_ASYNC_EMBEDDING,
        concurrent_requests=request.app.state.config.RAG_EMBEDDING_CONCURRENT_REQUESTS,
    )

    # Generate embeddings (async → sync bridge via the main event loop)
    future = asyncio.run_coroutine_threadsafe(
        embedding_function(
            [t.replace("\n", " ") for t in texts],
            prefix=RAG_EMBEDDING_CONTENT_PREFIX,
            user=user,
        ),
        request.app.state.main_loop,
    )
    embeddings = future.result(timeout=RAG_EMBEDDING_TIMEOUT)
    log.info(f"Generated {len(embeddings)} embedding(s) for collection '{collection_name}'")

    # Build items and insert
    items = [
        {
            "id": str(uuid.uuid4()),
            "text": text,
            "vector": embeddings[idx],
            "metadata": metadatas[idx],
        }
        for idx, text in enumerate(texts)
    ]

    VECTOR_DB_CLIENT.insert(
        collection_name=collection_name,
        items=items,
    )
    log.info(f"Stored {len(items)} item(s) in collection '{collection_name}'")
    return True


# ──────────────────────────────────────────────
#  4. Full pipeline: extract → chunk → embed → store
# ──────────────────────────────────────────────

def process_and_store(
    request,
    file_path: str,
    filename: str,
    content_type: str,
    collection_name: Optional[str] = None,
    chunk_size: int = 1500,
    chunk_overlap: int = 100,
    overwrite: bool = True,
    user=None,
) -> dict:
    """
    End-to-end RAG file processing pipeline.

    1. Extract text from the file
    2. Split into chunks
    3. Generate embeddings and store in vector DB

    Returns dict with collection_name, chunk_count, and text_content.
    """
    if collection_name is None:
        collection_name = f"rag-{uuid.uuid4().hex[:12]}"

    # Step 1: Extract
    docs = extract_text(file_path, filename, content_type)
    text_content = " ".join([doc.page_content for doc in docs])

    if not text_content.strip():
        raise ValueError(f"No text extracted from '{filename}'. File may be empty or unsupported.")

    # Step 2: Chunk
    # Enrich chunks with file metadata
    docs_with_meta = [
        Document(
            page_content=doc.page_content,
            metadata={
                **filter_metadata(doc.metadata),
                "name": filename,
                "source": filename,
            },
        )
        for doc in docs
    ]
    chunks = chunk_documents(docs_with_meta, chunk_size, chunk_overlap)

    # Step 3: Embed and store
    content_hash = calculate_sha256_string(text_content)
    embed_and_store(
        request,
        chunks,
        collection_name,
        metadata={
            "name": filename,
            "hash": content_hash,
        },
        overwrite=overwrite,
        user=user,
    )

    return {
        "collection_name": collection_name,
        "chunk_count": len(chunks),
        "text_length": len(text_content),
        "text_preview": text_content[:500],
    }


# ──────────────────────────────────────────────
#  5. Query — retrieve relevant chunks
# ──────────────────────────────────────────────

async def query_rag(
    request,
    collection_name: str,
    question: str,
    k: int = 5,
) -> dict:
    """
    Retrieve the top-k most relevant chunks for a question
    from a previously indexed collection.

    Uses the embedding function configured on the application state.
    """
    embedding_function = get_embedding_function(
        request.app.state.config.RAG_EMBEDDING_ENGINE,
        request.app.state.config.RAG_EMBEDDING_MODEL,
        request.app.state.ef,
        (
            request.app.state.config.RAG_OPENAI_API_BASE_URL
            if request.app.state.config.RAG_EMBEDDING_ENGINE == "openai"
            else (
                request.app.state.config.RAG_OLLAMA_BASE_URL
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "ollama"
                else request.app.state.config.RAG_AZURE_OPENAI_BASE_URL
            )
        ),
        (
            request.app.state.config.RAG_OPENAI_API_KEY
            if request.app.state.config.RAG_EMBEDDING_ENGINE == "openai"
            else (
                request.app.state.config.RAG_OLLAMA_API_KEY
                if request.app.state.config.RAG_EMBEDDING_ENGINE == "ollama"
                else request.app.state.config.RAG_AZURE_OPENAI_API_KEY
            )
        ),
        request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
        azure_api_version=(
            request.app.state.config.RAG_AZURE_OPENAI_API_VERSION
            if request.app.state.config.RAG_EMBEDDING_ENGINE == "azure_openai"
            else None
        ),
        enable_async=request.app.state.config.ENABLE_ASYNC_EMBEDDING,
        concurrent_requests=request.app.state.config.RAG_EMBEDDING_CONCURRENT_REQUESTS,
    )

    result = await query_collection(
        request=request,
        collection_names=[collection_name],
        queries=[question],
        embedding_function=embedding_function,
        k=k,
    )

    # Format results
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    chunks = []
    for i, doc in enumerate(documents):
        chunks.append({
            "text": doc,
            "metadata": metadatas[i] if i < len(metadatas) else {},
            "score": distances[i] if i < len(distances) else None,
        })

    return {
        "question": question,
        "collection_name": collection_name,
        "results_count": len(chunks),
        "chunks": chunks,
    }
