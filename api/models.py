from pydantic import BaseModel
from typing import Optional


class QueryRequest(BaseModel):
    question: str
    top_k: Optional[int] = 3


class SourceChunk(BaseModel):
    filename: str
    snippet: str
    chunk_index: int


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    processing_time_s: float


class DocumentMeta(BaseModel):
    doc_id: str
    filename: str
    chunk_count: int
    ingested_at: str


class IngestResponse(BaseModel):
    doc_id: str
    filename: str
    chunk_count: int
    message: str


class DeleteResponse(BaseModel):
    doc_id: str
    message: str
