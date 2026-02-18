# VR-OPS RAG

RAG system for querying SOP documents. FastAPI handles all AI/query logic; Streamlit is a simple UI for managing documents.

---

## Requirements

- [Python 3.11+](https://www.python.org/downloads/)
- [Ollama](https://ollama.com/download) installed and running

---

## First-time setup

```bash
# 1. Pull the required Ollama models
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Running the app

You need **two terminals** — one for the API, one for the dashboard.

**Terminal 1 — API:**
```bash
.venv\Scripts\activate
uvicorn api.main:app --reload
```
API is now live at `http://localhost:8000`
Interactive docs: `http://localhost:8000/docs`

**Terminal 2 — Dashboard:**
```bash
.venv\Scripts\activate
streamlit run dashboard/app.py
```
Dashboard is now live at `http://localhost:8501`

---

## Usage

### Streamlit dashboard
Go to `http://localhost:8501` to upload or delete SOP documents (.docx or .pdf).

### Query via terminal

**Ingest a document:**
```bash
curl -X POST http://localhost:8000/documents/ingest \
  -F "file=@SOPs/Document.docx"
```

**List ingested documents:**
```bash
curl http://localhost:8000/documents
```

**Ask a question:**
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"What are the steps for X?\"}"
```

**Delete a document** (use the `doc_id` returned from ingest or list):
```bash
curl -X DELETE http://localhost:8000/documents/{doc_id}
```

---

## Configuration

Settings live in `.env` (copied from `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server address |
| `LLM_MODEL` | `llama3.2:3b` | Model used for generating answers |
| `EMBED_MODEL` | `nomic-embed-text` | Model used for embeddings |
| `CHROMA_PATH` | `./data/chroma` | Where the vector store is saved on disk |
