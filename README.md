# Pythia

In Ancient Greece, Pythia was the Oracle of Delphi — the figure you consulted
when you needed answers from a vast and complex body of knowledge. You asked a
question; she gave you meaning, not just facts.

Pythia is a semantic search tool for WG21 C++ proposals. Instead of grepping for
keywords, you ask questions in plain English — "how does P2300 model cancellation?"
or "what are the safety arguments for profiles?" — and get back the most relevant
passages from across the paper corpus, ranked by meaning rather than exact match.

It also maps the citation graph between papers, so you can see which proposals
depend on or supersede each other, and flag papers that are referenced but not
yet in the index.

---

## How It Works

PDFs are parsed and split into labelled sections (motivation, proposal, wording,
etc.), then embedded using `sentence-transformers` and stored in Qdrant. At query
time, the question is embedded and matched against the index. Results are
optionally reranked by Cohere for better relevance. A citation graph is built
from cross-references between papers and serialized alongside the index.

| Layer          | Technology                                   |
|----------------|----------------------------------------------|
| Embeddings     | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| Vector store   | Qdrant (Docker)                              |
| Reranking      | Cohere (`rerank-english-v3.0`) — optional    |
| Citation graph | NetworkX                                     |
| API            | FastAPI                                      |
| UI             | Streamlit                                    |

---

## Corpus

20 papers covering:

| Area                     | Papers                            |
|--------------------------|-----------------------------------|
| Async / execution        | P2300, P2444                      |
| Coroutines               | P0057                             |
| Ranges                   | P0896                             |
| Safety / profiles        | P3081                             |
| Concurrency              | P1492, P1493, P2762, P2816, P2899 |
| Foundational / direction | P0939, N4685, and others          |

---

## Setup

You will need Python 3.14+ and Docker. Install dependencies and start Qdrant:

```bash
uv sync
docker compose up -d
```

Cohere reranking is optional but improves result quality. If you have a key,
set it before starting the API. Without it, results fall back to vector score order.

```bash
export COHERE_API_KEY=<your-key>
```

---

## Ingest

Before the app can search anything, the PDFs need to be parsed, chunked,
embedded, and loaded into Qdrant. This also builds the citation graph and writes
it to `graph.json`. It takes ~5–10 minutes on the first run and is safe to re-run —
the collection is wiped and rebuilt from scratch each time.

```bash
python ingest.py
```

---

## Run

The API and UI run as separate processes. Start the API first:

```bash
uvicorn main:app --reload
```

Then start the UI in a second terminal:

```bash
streamlit run app.py
```

| Service          | URL                               |
|------------------|-----------------------------------|
| UI               | `http://localhost:8501`           |
| API              | `http://localhost:8000`           |
| Swagger UI       | `http://localhost:8000/docs`      |
| Qdrant dashboard | `http://localhost:6333/dashboard` |

---

## Using the UI

### Search Tab
Type a query in plain English, or leave it blank and use the sidebar filters to
browse by section type, status, author, or date range. Results appear as
expandable cards showing the paper, section, relevance score, and the matched
passage.

Useful filter combinations:
- `section_type: motivation` — find the problem statements across proposals
- `section_type: wording` — normative text only
- `status: accepted` + a query — limit results to merged proposals

### Paper Tab
Enter a paper ID (e.g. `P2300R7`) to see its metadata and full citation table.
Papers it cites and papers that cite it are listed separately. Boundary nodes —
papers referenced in the corpus but not indexed — are highlighted in red.

### Corpus Tab
A table of everything currently indexed. Use this to confirm ingestion ran
correctly and to see what's available before searching.

---

## Qdrant Dashboard

The Qdrant web UI at `http://localhost:6333/dashboard` lets you inspect the
`wg21_papers` collection directly — browse indexed vectors, view chunk metadata,
and run test queries to verify the corpus loaded correctly after ingestion.

---

## API

The FastAPI backend is callable independently of the UI. Full interactive docs
are available at `http://localhost:8000/docs`.

### `POST /search`

Semantic search with optional filters and Cohere reranking. Leave `query` blank
to browse by filters only.

```json
{
  "query": "sender/receiver async model",
  "filters": {
    "section_type": "motivation",
    "status": "accepted"
  },
  "top_n": 5
}
```

Supported filter keys: `status`, `section_type`, `author`, `date_from`, `date_to`.

### `GET /papers/{paper_id}`
Returns metadata and citation neighbours for a single paper.

### `GET /graph/{paper_id}`
Returns the citation graph for a paper — cites and cited-by — with boundary
nodes flagged.

### `GET /corpus`
Returns all indexed papers with metadata.

---

## Project Structure

```
data/papers/       raw PDFs
models.py          Section and Paper dataclasses
ingest.py          ingestion pipeline
retrieval.py       search, rerank, graph_context
main.py            FastAPI app
app.py             Streamlit UI
docker-compose.yml Qdrant
graph.json         citation graph (generated by ingest.py)
```
