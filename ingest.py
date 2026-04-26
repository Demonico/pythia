"""
WG21 C++ Papers RAG — Phase 3 Ingestion Pipeline
Run: python ingest.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Allow running from the project root even if models.py lives one level up
# ---------------------------------------------------------------------------
_here = Path(__file__).parent
_root = Path(__file__).parent.parent  # main project root
for _p in (_here, _root):
    if (_p / "models.py").exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import networkx as nx
import pdfplumber
from models import Paper, Section
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PAPERS_DIR = Path(__file__).parent / "data" / "papers"
GRAPH_OUT = Path(__file__).parent / "graph.json"
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION = "wg21_papers"
VECTOR_SIZE = 384
EMBED_MODEL = "all-MiniLM-L6-v2"
MIN_CHUNK_LEN = 50

# Map keywords to canonical section_type labels
SECTION_TYPE_KEYWORDS: dict[str, list[str]] = {
    "abstract": ["abstract"],
    "motivation": ["motivation", "rationale", "background", "problem"],
    "introduction": ["introduction", "overview"],
    "proposal": ["proposal", "proposed", "design", "solution", "approach"],
    "wording": ["wording", "proposed wording", "formal wording", "normative"],
    "discussion": ["discussion", "alternatives", "open questions", "future"],
}


# ---------------------------------------------------------------------------
# Step 1 + 2: Parse PDF and extract metadata
# ---------------------------------------------------------------------------

_PAPER_ID_RE = re.compile(r"\b([Pp]\d{3,5}[Rr]\d+|[Nn]\d{3,5})\b")
_DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\w+ \d{1,2},?\s+\d{4}|\d{1,2} \w+ \d{4})\b"
)


def _derive_id_from_filename(pdf_path: Path) -> str:
    stem = pdf_path.stem  # e.g. p2300r7, n4685
    m = re.match(r"([pPnN]\d+[rR]?\d*)", stem)
    if m:
        return m.group(1).upper().replace("R", "R")  # normalise case
    return stem.upper()


def _normalise_paper_id(raw: str) -> str:
    """Uppercase and ensure consistent format, e.g. p2300r7 -> P2300R7."""
    return raw.upper()


def _classify_status(first_page_text: str) -> str:
    lower = first_page_text.lower()
    if "accepted" in lower:
        return "accepted"
    if "rejected" in lower:
        return "rejected"
    return "pending"


def parse_pdf(pdf_path: Path) -> tuple[list[str], dict]:
    """Return (pages_text, raw_meta) where pages_text[i] is page i+1 text."""
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return pages


def extract_metadata(pages: list[str], pdf_path: Path) -> dict:
    front = "\n".join(pages[:3])

    # Paper ID
    ids = _PAPER_ID_RE.findall(front)
    paper_id = _normalise_paper_id(ids[0]) if ids else _derive_id_from_filename(pdf_path)

    # Title — heuristic: first non-empty line of page 1 that looks like a title
    title = ""
    for line in pages[0].splitlines():
        line = line.strip()
        if len(line) > 10 and not _PAPER_ID_RE.match(line):
            title = line
            break

    # Authors — look for "Author:" / "Authors:" or lines after the paper-id block
    authors: list[str] = []
    author_match = re.search(
        r"(?:Authors?|Editor|Editors?)\s*[:\-]?\s*(.+)", front, re.IGNORECASE
    )
    if author_match:
        raw_authors = author_match.group(1)
        # split on commas, semicolons, "and"
        authors = [
            a.strip()
            for a in re.split(r"[,;]|\band\b", raw_authors)
            if a.strip() and len(a.strip()) < 80
        ]

    # Date
    date_matches = _DATE_RE.findall(front)
    date = date_matches[0] if date_matches else ""

    # Status
    status = _classify_status(pages[0])

    return {
        "paper_id": paper_id,
        "title": title,
        "authors": authors,
        "date": date,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Step 3: Chunk by section
# ---------------------------------------------------------------------------

# Patterns that indicate a section header
_HEADER_PATTERNS = [
    re.compile(r"^(\d+(\.\d+)*)\s+[A-Z][A-Za-z]"),   # numbered heading
    re.compile(r"^[A-Z][A-Z\s\-/:]{4,}$"),             # ALL CAPS line
    re.compile(r"^[A-Z][^.!?]{3,60}$"),                # short line no end punct
]


def _is_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) < 3:
        return False
    for pat in _HEADER_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def _classify_section_type(header: str) -> str:
    lower = header.lower()
    for stype, keywords in SECTION_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return stype
    return "other"


def chunk_sections(pages: list[str], paper_id: str) -> list[Section]:
    """Split all pages into Section objects detected by header lines."""
    sections: list[Section] = []

    current_header = "PREAMBLE"
    current_lines: list[str] = []
    current_page = 1

    def flush(page_number: int) -> None:
        content = "\n".join(current_lines).strip()
        if len(content) >= MIN_CHUNK_LEN:
            stype = _classify_section_type(current_header)
            sections.append(
                Section(
                    paper_id=paper_id,
                    section_type=stype,
                    content=content,
                    page_number=page_number,
                )
            )

    for page_num, page_text in enumerate(pages, start=1):
        for line in page_text.splitlines():
            if _is_header(line):
                flush(current_page)
                current_header = line.strip()
                current_lines = [line]
                current_page = page_num
            else:
                current_lines.append(line)

    flush(current_page)
    return sections


# ---------------------------------------------------------------------------
# Step 4: Extract citations
# ---------------------------------------------------------------------------

_CITATION_RE = re.compile(r"\b([Pp]\d{3,5}[Rr]?\d*|[Nn]\d{3,5})\b")


def extract_citations(pages: list[str]) -> list[str]:
    full_text = "\n".join(pages)
    raw = _CITATION_RE.findall(full_text)
    return list({_normalise_paper_id(c) for c in raw})


# ---------------------------------------------------------------------------
# Step 5: Embed and store
# ---------------------------------------------------------------------------

def _point_id(paper_id: str, section_type: str, page_number: int) -> str:
    name = f"{paper_id}:{section_type}:{page_number}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


def setup_qdrant(client: QdrantClient) -> None:
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION in existing:
        print(f"  [qdrant] Deleting existing collection '{COLLECTION}' for idempotency.")
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    print(f"  [qdrant] Created collection '{COLLECTION}'.")


def embed_and_store(
    papers: list[Paper],
    model: SentenceTransformer,
    client: QdrantClient,
) -> int:
    total_chunks = 0
    for paper in papers:
        if not paper.sections:
            continue
        texts = [s.content for s in paper.sections]
        embeddings = model.encode(texts, show_progress_bar=False)
        points = []
        for section, vector in zip(paper.sections, embeddings):
            pid = _point_id(paper.paper_id, section.section_type, section.page_number)
            points.append(
                PointStruct(
                    id=pid,
                    vector=vector.tolist(),
                    payload={
                        "paper_id": paper.paper_id,
                        "title": paper.title,
                        "section_type": section.section_type,
                        "page_number": section.page_number,
                        "status": paper.status,
                        "authors": paper.authors,
                    },
                )
            )
        client.upsert(collection_name=COLLECTION, points=points)
        total_chunks += len(points)
    return total_chunks


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(papers: list[Paper], corpus_ids: set[str]) -> nx.DiGraph:
    G = nx.DiGraph()
    for paper in papers:
        G.add_node(
            paper.paper_id,
            boundary=False,
            title=paper.title,
            authors=paper.authors,
            date=paper.date,
            status=paper.status,
        )

    boundary_nodes: set[str] = set()
    for paper in papers:
        for cited_id in paper.citations:
            if cited_id == paper.paper_id:
                continue
            if cited_id not in corpus_ids:
                boundary_nodes.add(cited_id)
                if not G.has_node(cited_id):
                    G.add_node(cited_id, boundary=True)
            G.add_edge(paper.paper_id, cited_id)

    return G, boundary_nodes


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    pdf_files = sorted(PAPERS_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {PAPERS_DIR}. Aborting.")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF files in {PAPERS_DIR}\n")

    # Load embedding model once
    print("Loading sentence-transformer model…")
    model = SentenceTransformer(EMBED_MODEL)

    # Connect to Qdrant
    print(f"Connecting to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}…")
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    setup_qdrant(client)
    print()

    papers: list[Paper] = []

    for pdf_path in pdf_files:
        print(f"Processing: {pdf_path.name}")

        # Steps 1 + 2
        pages = parse_pdf(pdf_path)
        meta = extract_metadata(pages, pdf_path)

        # Step 3
        sections = chunk_sections(pages, meta["paper_id"])
        print(f"  chunks: {len(sections)}")

        # Step 4
        citations = extract_citations(pages)
        # Remove self-reference
        citations = [c for c in citations if c != meta["paper_id"]]

        paper = Paper(
            paper_id=meta["paper_id"],
            title=meta["title"],
            authors=meta["authors"],
            date=meta["date"],
            status=meta["status"],
            sections=sections,
            citations=citations,
        )
        papers.append(paper)

    # Step 5 — embed + store
    print("\nEmbedding and storing chunks in Qdrant…")
    total_chunks = embed_and_store(papers, model, client)

    # Build citation graph
    corpus_ids = {p.paper_id for p in papers}
    G, boundary_nodes = build_graph(papers, corpus_ids)

    # Serialize graph
    data = nx.node_link_data(G)
    with open(GRAPH_OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Graph serialized to {GRAPH_OUT}")

    # Summary
    total_edges = G.number_of_edges()
    print("\n" + "=" * 50)
    print("INGESTION SUMMARY")
    print("=" * 50)
    print(f"  Total papers   : {len(papers)}")
    print(f"  Total chunks   : {total_chunks}")
    print(f"  Total edges    : {total_edges}")
    print(f"  Boundary nodes : {len(boundary_nodes)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
