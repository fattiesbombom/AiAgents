"""Chunk a PDF, embed with Ollama (same model as sop_retrieval), insert into input DB sop_documents.

Prerequisites
-------------
- PostgreSQL input DB with ``input_schema.sql`` applied (pgvector + sop_documents).
- ``INPUT_DB_URL`` in environment (or ``security-ai-system/.env`` via pydantic-settings).
- Ollama running with the embedding model pulled, e.g.::

    ollama pull nomic-embed-text

- Default model/dimension must match ``backend.config.settings`` (768-d for nomic-embed-text).

Run (from ``security-ai-system`` repo root)::

    python -m backend.scripts.ingest_sop_pdf path/to/sop.pdf --title "Site security SOP"

Replace previous rows for the same logical document::

    python -m backend.scripts.ingest_sop_pdf path/to/sop.pdf --source-key certis-site-sop --replace
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from langchain_ollama import OllamaEmbeddings
from pypdf import PdfReader

from backend.config import settings


def _extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n\n".join(parts).strip()


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    if chunk_size < 200:
        chunk_size = 200
    if overlap < 0 or overlap >= chunk_size:
        overlap = max(0, chunk_size // 5)
    chunks: list[str] = []
    i = 0
    while i < len(text):
        piece = text[i : i + chunk_size].strip()
        if piece:
            chunks.append(piece)
        i += chunk_size - overlap
    return chunks


def _vector_sql(values: list[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a PDF into sop_documents (vector RAG).")
    parser.add_argument("pdf", type=Path, help="Path to the PDF file")
    parser.add_argument("--title", type=str, default=None, help="Title stored on every chunk (default: PDF stem)")
    parser.add_argument(
        "--source-key",
        type=str,
        default=None,
        help="Value for source_file column / idempotency key (default: PDF path resolved)",
    )
    parser.add_argument("--chunk-size", type=int, default=1200, help="Characters per chunk (default 1200)")
    parser.add_argument("--overlap", type=int, default=200, help="Character overlap between chunks")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing rows with this source_key before inserting",
    )
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    if not pdf_path.is_file():
        print(f"File not found: {pdf_path}", file=sys.stderr)
        return 1

    source_key = args.source_key or str(pdf_path)
    title = args.title or pdf_path.stem.replace("_", " ").title()

    try:
        raw = _extract_pdf_text(pdf_path)
    except Exception as e:
        print(f"Failed to read PDF: {e}", file=sys.stderr)
        return 1

    chunks = _chunk_text(raw, args.chunk_size, args.overlap)
    if not chunks:
        print("No text extracted from PDF (empty or unreadable).", file=sys.stderr)
        return 1

    embedder = OllamaEmbeddings(
        model=settings.EMBEDDING_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
    )

    try:
        embeddings = embedder.embed_documents(chunks)
    except Exception as e:
        print(
            f"Embedding failed ({e}). Is Ollama running? Try: ollama pull {settings.EMBEDDING_MODEL}",
            file=sys.stderr,
        )
        return 1

    if len(embeddings) != len(chunks):
        print("Embedding count mismatch.", file=sys.stderr)
        return 1

    dim = settings.EMBEDDING_DIMENSIONS
    for i, emb in enumerate(embeddings):
        if len(emb) != dim:
            print(
                f"Chunk {i}: expected {dim}-d embedding, got {len(emb)}. "
                f"Align EMBEDDING_DIMENSIONS / model with input_schema vector({dim}).",
                file=sys.stderr,
            )
            return 1

    try:
        import psycopg
    except ImportError:
        print("psycopg is required (install from requirements.txt).", file=sys.stderr)
        return 1

    now = datetime.now(UTC)
    inserted = 0

    with psycopg.connect(settings.INPUT_DB_URL) as conn:
        with conn.cursor() as cur:
            if args.replace:
                cur.execute("DELETE FROM sop_documents WHERE source_file = %s", (source_key,))
            for idx, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=True)):
                vec = _vector_sql([float(x) for x in emb])
                cur.execute(
                    """
                    INSERT INTO sop_documents (id, title, source_file, chunk_index, content, embedding, created_at)
                    VALUES (CAST(%s AS uuid), %s, %s, %s, %s, CAST(%s AS vector), %s)
                    """,
                    (str(uuid4()), title, source_key, idx, chunk, vec, now),
                )
                inserted += 1
        conn.commit()

    print(f"Inserted {inserted} chunks into sop_documents (title={title!r}, source_file={source_key!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
