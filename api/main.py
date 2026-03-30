"""
FastAPI app — RAG endpoints for SOP documents.
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()  # must run before rag is imported (reads env vars at module level)

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

from api.models import (
    DeleteResponse,
    DocumentMeta,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    SourceChunk,
)
from api import rag


@asynccontextmanager
async def lifespan(app: FastAPI):
    rag.get_collection()
    rag.embed(["warmup"])  # pre-establish HTTPS connection to OpenAI
    yield


app = FastAPI(
    title="VR-OPS RAG API",
    description="RAG API for querying SOP documents via OpenAI + ChromaDB",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@app.post("/query", response_model=QueryResponse)
async def query_documents(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    try:
        result = rag.query(req.question, top_k=req.top_k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return QueryResponse(
        answer=result["answer"],
        sources=[SourceChunk(**s) for s in result["sources"]],
        processing_time_s=result["processing_time_s"],
    )


# ---------------------------------------------------------------------------
# Document management
# ---------------------------------------------------------------------------

@app.get("/documents", response_model=list[DocumentMeta])
async def list_documents():
    try:
        docs = rag.list_documents()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return [DocumentMeta(**d) for d in docs]


@app.get("/documents/{doc_id}/download")
async def download_document(doc_id: str):
    result = rag.get_document_file(doc_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Original file not available for download.")
    file_path, filename = result
    return FileResponse(file_path, filename=filename, media_type="application/octet-stream")


@app.post("/documents/ingest", response_model=IngestResponse)
async def ingest_document(file: UploadFile = File(...)):
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in {"docx", "pdf"}:
        raise HTTPException(status_code=400, detail="Only .docx and .pdf files are supported.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        meta = rag.ingest_document(filename, data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return IngestResponse(
        doc_id=meta["doc_id"],
        filename=meta["filename"],
        chunk_count=meta["chunk_count"],
        message=f"Ingested {meta['chunk_count']} chunks from '{filename}'.",
    )


@app.delete("/documents/{doc_id}", response_model=DeleteResponse)
async def delete_document(doc_id: str):
    try:
        deleted = rag.delete_document(doc_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"No document found with id '{doc_id}'.")

    return DeleteResponse(
        doc_id=doc_id,
        message=f"Deleted {deleted} chunks for document '{doc_id}'.",
    )
