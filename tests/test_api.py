"""
Tests for VR-OPS RAG system.

- Unit tests: chunking, parsing, model validation, API contract
- Benchmark tests: 10 real queries against the deployed API at 10.44.122.161
  including irrelevant questions to validate the AI refuses to hallucinate.
"""

import time
import pytest
import requests

from api.models import QueryRequest, QueryResponse, SourceChunk, DocumentMeta
from api.rag import chunk_text, _split

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "http://10.44.122.161/api"
QUERY_TIMEOUT = 30  # seconds


# ===========================================================================
# Unit Tests
# ===========================================================================


class TestChunking:
    """Unit tests for the text chunking logic."""

    def test_short_text_returns_single_chunk(self):
        text = "This is a short sentence."
        chunks = chunk_text(text, size=800, overlap=150)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_text_returns_no_chunks(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_chunks_respect_max_size(self):
        # Build a long text with many paragraphs
        text = "\n\n".join([f"Paragraph {i} with some filler content." for i in range(100)])
        chunks = chunk_text(text, size=200, overlap=30)
        for chunk in chunks:
            assert len(chunk) <= 200 + 50, f"Chunk too long: {len(chunk)} chars"

    def test_chunks_cover_full_text(self):
        words = [f"word{i}" for i in range(200)]
        text = " ".join(words)
        chunks = chunk_text(text, size=100, overlap=20)
        # Every word should appear in at least one chunk
        combined = " ".join(chunks)
        for word in words:
            assert word in combined, f"Missing word: {word}"

    def test_overlap_exists_between_consecutive_chunks(self):
        text = " ".join([f"w{i}" for i in range(300)])
        chunks = chunk_text(text, size=100, overlap=30)
        if len(chunks) >= 2:
            # The end of chunk[0] should share content with the start of chunk[1]
            tail = chunks[0][-30:]
            assert any(
                part in chunks[1] for part in tail.split()
            ), "No overlap detected between consecutive chunks"

    def test_paragraph_boundary_splitting(self):
        text = "First paragraph content here.\n\nSecond paragraph content here."
        chunks = chunk_text(text, size=40, overlap=5)
        assert len(chunks) >= 2


class TestModels:
    """Unit tests for Pydantic models."""

    def test_query_request_defaults(self):
        req = QueryRequest(question="What is a compressor?")
        assert req.question == "What is a compressor?"
        assert req.top_k == 2

    def test_query_request_custom_top_k(self):
        req = QueryRequest(question="Test", top_k=5)
        assert req.top_k == 5

    def test_source_chunk_model(self):
        sc = SourceChunk(filename="test.pdf", snippet="some text", chunk_index=3)
        assert sc.filename == "test.pdf"
        assert sc.chunk_index == 3

    def test_query_response_model(self):
        resp = QueryResponse(
            answer="The answer is 42.",
            sources=[SourceChunk(filename="doc.pdf", snippet="...", chunk_index=0)],
            processing_time_s=1.23,
        )
        assert resp.processing_time_s == 1.23
        assert len(resp.sources) == 1

    def test_document_meta_model(self):
        dm = DocumentMeta(
            doc_id="abc-123",
            filename="sop.docx",
            chunk_count=10,
            ingested_at="2025-01-01T00:00:00Z",
        )
        assert dm.chunk_count == 10


# ===========================================================================
# API Integration Tests (deployed instance)
# ===========================================================================


def _query_api(question: str, top_k: int = 3) -> dict:
    """Helper: POST a question to the deployed API and return the response dict + timing."""
    start = time.perf_counter()
    resp = requests.post(
        f"{BASE_URL}/query",
        json={"question": question, "top_k": top_k},
        timeout=QUERY_TIMEOUT,
    )
    wall_time = time.perf_counter() - start
    resp.raise_for_status()
    data = resp.json()
    data["_wall_time_s"] = round(wall_time, 2)
    return data


class TestAPIHealth:
    """Basic API contract tests against the deployed instance."""

    def test_documents_endpoint(self):
        resp = requests.get(f"{BASE_URL}/documents", timeout=10)
        assert resp.status_code == 200
        docs = resp.json()
        assert isinstance(docs, list)
        assert len(docs) > 0, "No documents ingested — RAG has nothing to search"

    def test_query_returns_expected_shape(self):
        data = _query_api("What is a compressor?")
        assert "answer" in data
        assert "sources" in data
        assert "processing_time_s" in data
        assert isinstance(data["sources"], list)

    def test_empty_question_rejected(self):
        resp = requests.post(
            f"{BASE_URL}/query",
            json={"question": "   "},
            timeout=10,
        )
        assert resp.status_code == 400


# ===========================================================================
# Benchmark Tests — 10 questions against the deployed AI
# ===========================================================================

# Questions 1-6: relevant to oil & gas SOPs / Alberta Shale Gathering
# Questions 7-10: irrelevant — the AI should NOT answer these from SOP context

BENCHMARK_QUESTIONS = [
    # --- Relevant questions (should get real answers) ---
    {
        "id": 1,
        "question": "What are the steps to start a two-stage centrifugal compressor?",
        "relevant": True,
        "expect_keywords": ["step", "compressor"],
    },
    {
        "id": 2,
        "question": "What safety precautions should be taken before starting equipment?",
        "relevant": True,
        "expect_keywords": ["safety"],
    },
    {
        "id": 3,
        "question": "What does 'blowdown' mean in the context of gas gathering?",
        "relevant": True,
        "expect_keywords": [],
    },
    {
        "id": 4,
        "question": "How do you perform a line break procedure?",
        "relevant": True,
        "expect_keywords": [],
    },
    {
        "id": 5,
        "question": "What is the purpose of a suction scrubber?",
        "relevant": True,
        "expect_keywords": [],
    },
    {
        "id": 6,
        "question": "What are the emergency shutdown procedures?",
        "relevant": True,
        "expect_keywords": ["shutdown"],
    },
    # --- Irrelevant questions (AI should refuse / say it can't answer) ---
    {
        "id": 7,
        "question": "What is the capital of France?",
        "relevant": False,
        "expect_keywords": [],
    },
    {
        "id": 8,
        "question": "Can you write me a Python script to sort a list?",
        "relevant": False,
        "expect_keywords": [],
    },
    {
        "id": 9,
        "question": "Who won the 2024 Super Bowl?",
        "relevant": False,
        "expect_keywords": [],
    },
    {
        "id": 10,
        "question": "What is the recipe for chocolate chip cookies?",
        "relevant": False,
        "expect_keywords": [],
    },
]

# Phrases the AI uses when it can't answer from context
REFUSAL_PHRASES = [
    "not found in the context",
    "not mentioned in the context",
    "not covered in the context",
    "not available in the context",
    "not provided in the context",
    "not included in the context",
    "does not contain",
    "do not have information",
    "don't have information",
    "no information",
    "cannot answer",
    "can't answer",
    "not in the provided",
    "outside the scope",
    "not related to",
    "no relevant information",
    "I cannot find",
    "I could not find",
    "not addressed",
    "beyond the scope",
]


def _looks_like_refusal(answer: str) -> bool:
    """Check if the answer indicates the AI declined to answer."""
    lower = answer.lower()
    return any(phrase in lower for phrase in REFUSAL_PHRASES)


class TestBenchmark:
    """
    Benchmark tests: 10 questions against the deployed RAG API.
    Validates answer quality, hallucination resistance, and response time.
    """

    @pytest.fixture(scope="class")
    def benchmark_results(self):
        """Run all 10 benchmark questions and collect results."""
        results = []
        for q in BENCHMARK_QUESTIONS:
            try:
                data = _query_api(q["question"], top_k=3)
                results.append({
                    **q,
                    "answer": data["answer"],
                    "sources": data["sources"],
                    "processing_time_s": data["processing_time_s"],
                    "wall_time_s": data["_wall_time_s"],
                    "error": None,
                })
            except Exception as e:
                results.append({**q, "answer": None, "error": str(e)})
        return results

    def test_all_queries_succeed(self, benchmark_results):
        """All 10 queries should return without error."""
        for r in benchmark_results:
            assert r["error"] is None, f"Q{r['id']} failed: {r['error']}"

    def test_relevant_questions_get_substantive_answers(self, benchmark_results):
        """Relevant questions (1-6) should return non-trivial answers."""
        for r in benchmark_results:
            if r["relevant"] and r["error"] is None:
                assert r["answer"] is not None
                assert len(r["answer"]) > 30, (
                    f"Q{r['id']}: Answer too short ({len(r['answer'])} chars) — "
                    f"expected substantive response"
                )

    def test_relevant_questions_have_sources(self, benchmark_results):
        """Relevant questions should cite SOP sources."""
        for r in benchmark_results:
            if r["relevant"] and r["error"] is None:
                assert len(r["sources"]) > 0, (
                    f"Q{r['id']}: No sources returned for a relevant question"
                )

    def test_relevant_questions_contain_expected_keywords(self, benchmark_results):
        """Relevant answers should contain expected domain keywords."""
        for r in benchmark_results:
            if r["relevant"] and r["error"] is None and r["expect_keywords"]:
                answer_lower = r["answer"].lower()
                for kw in r["expect_keywords"]:
                    assert kw.lower() in answer_lower, (
                        f"Q{r['id']}: Expected keyword '{kw}' not found in answer"
                    )

    def test_irrelevant_questions_are_refused(self, benchmark_results):
        """Irrelevant questions (7-10) should be refused — no hallucination."""
        for r in benchmark_results:
            if not r["relevant"] and r["error"] is None:
                assert _looks_like_refusal(r["answer"]), (
                    f"Q{r['id']}: AI should have refused but answered: "
                    f"{r['answer'][:150]}..."
                )

    def test_response_times_are_reasonable(self, benchmark_results):
        """All responses should come back within 15 seconds."""
        for r in benchmark_results:
            if r["error"] is None:
                assert r["wall_time_s"] < 15, (
                    f"Q{r['id']}: Response took {r['wall_time_s']}s — too slow"
                )

    def test_average_response_time(self, benchmark_results):
        """Average response time across all queries should be under 8 seconds."""
        times = [r["wall_time_s"] for r in benchmark_results if r["error"] is None]
        avg = sum(times) / len(times) if times else 0
        assert avg < 8, f"Average response time {avg:.2f}s exceeds 8s threshold"

    def test_benchmark_summary(self, benchmark_results, capsys):
        """Print a summary table of all benchmark results."""
        print("\n" + "=" * 90)
        print("BENCHMARK RESULTS")
        print("=" * 90)
        print(f"{'#':<4} {'Type':<12} {'Wall(s)':<10} {'API(s)':<10} {'Ans Len':<10} {'Result'}")
        print("-" * 90)
        for r in benchmark_results:
            if r["error"]:
                print(f"{r['id']:<4} {'—':<12} {'—':<10} {'—':<10} {'—':<10} ERROR: {r['error']}")
                continue

            qtype = "relevant" if r["relevant"] else "irrelevant"
            refused = _looks_like_refusal(r["answer"])
            if r["relevant"]:
                status = "PASS" if not refused and len(r["answer"]) > 30 else "FAIL"
            else:
                status = "PASS (refused)" if refused else "FAIL (hallucinated)"

            print(
                f"{r['id']:<4} {qtype:<12} {r['wall_time_s']:<10.2f} "
                f"{r['processing_time_s']:<10.2f} {len(r['answer']):<10} {status}"
            )

        times = [r["wall_time_s"] for r in benchmark_results if r["error"] is None]
        if times:
            print("-" * 90)
            print(f"     {'AVG':<12} {sum(times)/len(times):<10.2f}")
            print(f"     {'MAX':<12} {max(times):<10.2f}")
            print(f"     {'MIN':<12} {min(times):<10.2f}")
        print("=" * 90)

        # Print truncated answers
        print("\nANSWER PREVIEWS:")
        print("-" * 90)
        for r in benchmark_results:
            if r["error"] is None:
                preview = r["answer"][:200].replace("\n", " ")
                print(f"Q{r['id']}: {r['question']}")
                print(f"  → {preview}...")
                print()
