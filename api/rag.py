"""
RAG pipeline: ingestion, querying, deletion.
ChromaDB for vector storage, OpenAI for embeddings and generation.
"""

import io
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import chromadb
import openai as openai_module
from docx import Document as DocxDocument
from pypdf import PdfReader

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config (pulled from environment, set via .env)
# ---------------------------------------------------------------------------

CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma")
LLM_MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "400"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")  # e.g. http://localhost:11434
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text" if OLLAMA_BASE_URL else "text-embedding-3-small")

COLLECTION_NAME = "sops"
CHUNK_SIZE = 400       # characters
CHUNK_OVERLAP = 80     # characters


# ---------------------------------------------------------------------------
# ChromaDB client (singleton)
# ---------------------------------------------------------------------------

_chroma_client: Optional[chromadb.PersistentClient] = None
_collection: Optional[chromadb.Collection] = None
_openai: Optional[openai_module.OpenAI] = None
_embed: Optional[openai_module.OpenAI] = None


def get_collection() -> chromadb.Collection:
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


# ---------------------------------------------------------------------------
# OpenAI client (singleton)
# ---------------------------------------------------------------------------

def _openai_client() -> openai_module.OpenAI:
    global _openai
    if _openai is None:
        _openai = openai_module.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai


def _embed_client() -> openai_module.OpenAI:
    global _embed
    if _embed is None:
        if OLLAMA_BASE_URL:
            _embed = openai_module.OpenAI(base_url=f"{OLLAMA_BASE_URL}/v1", api_key="ollama")
        else:
            _embed = _openai_client()
    return _embed


# ---------------------------------------------------------------------------
# Document parsing
# ---------------------------------------------------------------------------

def parse_docx(data: bytes) -> str:
    doc = DocxDocument(io.BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def parse_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text and text.strip():
            pages.append(text.strip())
    return "\n\n".join(pages)


def extract_text(filename: str, data: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "docx":
        return parse_docx(data)
    if ext == "pdf":
        return parse_pdf(data)
    raise ValueError(f"Unsupported file type: .{ext}")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Recursive character splitter — splits on paragraph, then sentence, then word boundaries."""
    separators = ["\n\n", "\n", ". ", " ", ""]
    return _split(text, size, overlap, separators)


def _split(text: str, size: int, overlap: int, separators: list[str]) -> list[str]:
    if len(text) <= size:
        return [text] if text.strip() else []

    sep = ""
    for s in separators:
        if s in text:
            sep = s
            break

    parts = text.split(sep) if sep else list(text)
    chunks: list[str] = []
    current = ""

    for part in parts:
        candidate = current + (sep if current else "") + part
        if len(candidate) <= size:
            current = candidate
        else:
            if current.strip():
                chunks.append(current.strip())
            # carry overlap from end of current into next
            overlap_text = current[-overlap:] if len(current) > overlap else current
            current = overlap_text + (sep if overlap_text else "") + part

    if current.strip():
        chunks.append(current.strip())

    return chunks


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def embed(texts: list[str]) -> list[list[float]]:
    resp = _embed_client().embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in resp.data]


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def ingest_document(filename: str, data: bytes) -> dict:
    """Parse, chunk, embed, and store a document. Returns metadata."""
    text = extract_text(filename, data)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Document produced no text content after parsing.")

    doc_id = str(uuid.uuid4())
    ingested_at = datetime.now(timezone.utc).isoformat()

    embeddings = embed(chunks)

    collection = get_collection()
    collection.add(
        ids=[f"{doc_id}_{i}" for i in range(len(chunks))],
        embeddings=embeddings,
        documents=chunks,
        metadatas=[
            {
                "doc_id": doc_id,
                "filename": filename,
                "chunk_index": i,
                "ingested_at": ingested_at,
            }
            for i in range(len(chunks))
        ],
    )

    return {
        "doc_id": doc_id,
        "filename": filename,
        "chunk_count": len(chunks),
        "ingested_at": ingested_at,
    }


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

def delete_document(doc_id: str) -> int:
    """Delete all chunks for a doc_id. Returns number of chunks deleted."""
    collection = get_collection()
    results = collection.get(where={"doc_id": doc_id})
    ids = results.get("ids", [])
    if ids:
        collection.delete(ids=ids)
    return len(ids)


# ---------------------------------------------------------------------------
# Document listing
# ---------------------------------------------------------------------------

def list_documents() -> list[dict]:
    """Return one entry per unique doc_id with aggregated metadata."""
    collection = get_collection()
    results = collection.get(include=["metadatas"])
    metadatas = results.get("metadatas") or []

    docs: dict[str, dict] = {}
    for meta in metadatas:
        did = meta["doc_id"]
        if did not in docs:
            docs[did] = {
                "doc_id": did,
                "filename": meta["filename"],
                "chunk_count": 0,
                "ingested_at": meta["ingested_at"],
            }
        docs[did]["chunk_count"] += 1

    return list(docs.values())


# ---------------------------------------------------------------------------
# Query / RAG
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are an expert assistant for Standard Operating Procedures (SOPs). "
    "Answer questions accurately and concisely using only the provided context. "
    "If the answer is not found in the context, say so clearly. "
    "When describing procedures, use numbered steps. "
    "Do not make up information."
)


def query(question: str, top_k: int = 3) -> dict:
    """Embed question, retrieve top-k chunks, generate answer."""
    log.info("query start | llm=%s embed=%s top_k=%d", LLM_MODEL, EMBED_MODEL, top_k)

    t0 = time.perf_counter()

    # Embed question
    q_vec = embed([question])[0]
    t_embed = time.perf_counter() - t0
    log.info("  embed       %.3fs", t_embed)

    # Retrieve
    t1 = time.perf_counter()
    collection = get_collection()
    results = collection.query(
        query_embeddings=[q_vec],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas"],
    )
    t_retrieve = time.perf_counter() - t1
    log.info("  retrieve    %.3fs  (%d chunks)", t_retrieve, min(top_k, collection.count()))

    chunks = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []

    # Build context
    context_parts = []
    for i, (chunk, meta) in enumerate(zip(chunks, metas)):
        context_parts.append(f"[Source: {meta['filename']}, chunk {meta['chunk_index']}]\n{chunk}")
    context = "\n\n---\n\n".join(context_parts)

    # Generate
    t2 = time.perf_counter()
    response = _openai_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        max_tokens=MAX_TOKENS,
    )
    answer = response.choices[0].message.content
    t_generate = time.perf_counter() - t2

    elapsed = time.perf_counter() - t0
    log.info("  generate    %.3fs", t_generate)
    log.info("  TOTAL       %.3fs", elapsed)

    sources = [
        {
            "filename": m["filename"],
            "snippet": c[:200].replace("\n", " "),
            "chunk_index": m["chunk_index"],
        }
        for c, m in zip(chunks, metas)
    ]

    return {
        "answer": answer,
        "sources": sources,
        "processing_time_s": round(elapsed, 2),
    }
