# WG21 RAG Service — Build Spec

## Stack
- Python 3.11+
- FastAPI
- Qdrant (Docker, local)
- Streamlit
- `pdfplumber` for PDF parsing
- `sentence-transformers` for embeddings
- `cohere` for reranking
- `networkx` for citation graph

---

## Project Structure
```
wg21-rag/
├── data/
│   └── papers/          # raw PDFs
├── ingest.py            # ingestion pipeline
├── models.py            # data structures
├── retrieval.py         # search, reranking, graph
├── main.py              # FastAPI app
├── app.py               # Streamlit UI
├── requirements.txt
└── docker-compose.yml   # Qdrant only
```

---

## Phase 1 — Data
Curate ~20 papers across:
- Networking/async (P2300, P2444)
- Coroutines (P0057)
- Ranges (P0896)
- Safety/profiles (P3081)
- Foundational (SD-6, P0939)

Download PDFs from open-std.org manually. Drop in `data/papers/`.

---

## Phase 2 — Models

```python
# models.py
@dataclass
class Section:
    paper_id: str
    section_type: str  # motivation, proposal, wording, etc
    content: str
    page_number: int

@dataclass
class Paper:
    paper_id: str      # e.g. P2300R7
    title: str
    authors: list[str]
    date: str
    status: str        # accepted, rejected, pending
    sections: list[Section]
    citations: list[str]  # paper_ids cited
```

---

## Phase 3 — Ingestion

`ingest.py` executes five steps in sequence:

1. **Parse** — pdfplumber extracts text page by page
2. **Extract metadata** — regex for paper number, title, authors, date from front matter
3. **Chunk by section** — detect section headers, split content, tag each chunk with section type
4. **Extract citations** — regex for P-number and N-number references, build edges even for papers not in corpus, flag boundary nodes
5. **Embed and store** — sentence-transformers embeddings, store chunks in Qdrant with metadata payload, store citation graph with networkx, serialize to `graph.json`

---

## Phase 4 — Retrieval

`retrieval.py` exposes three functions:

### `search(query, filters=None, top_k=20)`
- Embed query
- Qdrant vector search with optional metadata filters (status, author, date, section_type)
- Return top_k candidates

### `rerank(query, candidates, top_n=5)`
- Cohere reranker pass over candidates
- Return top_n with scores

### `graph_context(paper_id)`
- Return papers this one cites
- Return papers that cite this one
- Flag boundary nodes explicitly

---

## Phase 5 — FastAPI

`main.py` exposes three endpoints:

### `POST /search`
```json
{
  "query": "string",
  "filters": {
    "status": "accepted",
    "section_type": "motivation"
  },
  "top_n": 5
}
```

### `GET /papers/{paper_id}`
Returns metadata and citation graph for a specific paper.

### `GET /graph/{paper_id}`
Returns citation relationships with boundary nodes flagged.

---

## Phase 6 — Streamlit

`app.py` has three tabs:

### Search Tab
- Text input for query
- Sidebar filters: status, section type, date range
- Results displayed as expandable cards showing paper ID, title, section type, relevance score, and content snippet

### Paper Tab
- Select paper by ID
- Show metadata
- Show citation graph as a table — cites / cited by / boundary nodes flagged in red

### Corpus Tab
- Table of all indexed papers with metadata
- Confirms what is in the index

---

## Phase 7 — Loom

Demo flow:
1. Show Qdrant dashboard — corpus is real
2. Corpus tab — here's what's indexed
3. Search tab — run a query, show section-aware results
4. Filter by section type — show motivation sections only
5. Paper tab — show citation graph, highlight a boundary node, explain the design decision
6. Swagger UI — show the API exists and is callable by other tools
