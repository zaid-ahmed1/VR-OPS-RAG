"""
Streamlit dashboard — SOP document manager.
Thin client: all logic lives in the FastAPI backend.
"""

import requests
import streamlit as st

API_BASE = "http://localhost:8000"


def fetch_documents() -> list[dict]:
    try:
        resp = requests.get(f"{API_BASE}/documents", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach API at " + API_BASE + ". Is it running?")
        return []
    except Exception as e:
        st.error(f"Error fetching documents: {e}")
        return []


def ingest_file(file) -> tuple[bool, str]:
    try:
        resp = requests.post(
            f"{API_BASE}/documents/ingest",
            files={"file": (file.name, file.getvalue(), file.type)},
            timeout=120,
        )
        if resp.ok:
            data = resp.json()
            return True, data.get("message", "Ingested successfully.")
        return False, resp.json().get("detail", "Unknown error.")
    except requests.exceptions.ConnectionError:
        return False, "Cannot reach API."
    except Exception as e:
        return False, str(e)


def delete_document(doc_id: str, filename: str) -> tuple[bool, str]:
    try:
        resp = requests.delete(f"{API_BASE}/documents/{doc_id}", timeout=10)
        if resp.ok:
            return True, f"'{filename}' removed."
        return False, resp.json().get("detail", "Unknown error.")
    except requests.exceptions.ConnectionError:
        return False, "Cannot reach API."
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="VR-OPS SOP Manager", page_icon="📋", layout="centered")
st.title("📋 SOP Document Manager")
st.caption("Add or remove Standard Operating Procedure documents from the RAG system.")

st.divider()

# --- Upload section ---
st.subheader("Add SOP")
uploaded = st.file_uploader(
    "Upload a .docx or .pdf file",
    type=["docx", "pdf"],
    accept_multiple_files=False,
)

if uploaded:
    st.write(f"**File:** `{uploaded.name}` ({uploaded.size:,} bytes)")
    if st.button("Ingest into RAG", type="primary"):
        with st.spinner(f"Ingesting `{uploaded.name}`… this may take a moment."):
            ok, msg = ingest_file(uploaded)
        if ok:
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)

st.divider()

# --- Document list ---
st.subheader("Ingested SOPs")

docs = fetch_documents()

if not docs:
    st.info("No documents ingested yet. Upload one above.")
else:
    for doc in docs:
        col_name, col_chunks, col_date, col_del = st.columns([3, 1, 2, 1])
        col_name.write(f"**{doc['filename']}**")
        col_chunks.write(f"{doc['chunk_count']} chunks")
        # Show date only (strip time from ISO string)
        date_str = doc.get("ingested_at", "")[:10]
        col_date.write(date_str)

        if col_del.button("Delete", key=doc["doc_id"], type="secondary"):
            with st.spinner(f"Removing `{doc['filename']}`…"):
                ok, msg = delete_document(doc["doc_id"], doc["filename"])
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
