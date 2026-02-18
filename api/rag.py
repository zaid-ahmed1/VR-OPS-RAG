"""
RAG pipeline: ingestion, querying, deletion.
No LangChain — raw ChromaDB + Ollama clients for minimal overhead.
"""

import io
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import chromadb
import ollama
from docx import Document as DocxDocument
from pypdf import PdfReader


# ---------------------------------------------------------------------------
# Config (pulled from environment, set via .env)
# ---------------------------------------------------------------------------

CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

COLLECTION_NAME = "sops"
CHUNK_SIZE = 600       # characters
CHUNK_OVERLAP = 80     # characters


# ---------------------------------------------------------------------------
# ChromaDB client (singleton)
# ---------------------------------------------------------------------------

_chroma_client: Optional[chromadb.PersistentClient] = None
_collection: Optional[chromadb.Collection] = None


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
# Ollama client
# ---------------------------------------------------------------------------

def _ollama_client() -> ollama.Client:
    return ollama.Client(host=OLLAMA_BASE_URL)


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
    client = _ollama_client()
    vectors = []
    for text in texts:
        resp = client.embeddings(model=EMBED_MODEL, prompt=text)
        vectors.append(resp["embedding"])
    return vectors


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


def query(question: str, top_k: int = 4) -> dict:
    """Embed question, retrieve top-k chunks, generate answer."""
    import time
    start = time.perf_counter()

    # Embed question
    q_vec = embed([question])[0]

    # Retrieve
    collection = get_collection()
    results = collection.query(
        query_embeddings=[q_vec],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas"],
    )

    chunks = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []

    # Build context
    context_parts = []
    for i, (chunk, meta) in enumerate(zip(chunks, metas)):
        context_parts.append(f"[Source: {meta['filename']}, chunk {meta['chunk_index']}]\n{chunk}")
    context = "\n\n---\n\n".join(context_parts)

    # Generate
    client = _ollama_client()
    response = client.chat(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {question}",
            },
        ],
    )

    answer = response["message"]["content"]
    elapsed = time.perf_counter() - start

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
