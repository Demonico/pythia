# Parallelization Plan for WG21 RAG Phases 2–7

## Context
Phase 1 of `docs/WG21-RAG-SPEC.md` is complete: 20 PDFs are in `data/papers/`. The
repo currently contains only a FastAPI hello-world stub (`main.py`), `pyproject.toml`,
and `uv.lock`. The user is asking whether the remaining phases (2–7) can be
executed in parallel to compress wall-clock time.

The phases as written look sequential, but several have no real dependency on
each other once the data contract (Phase 2) is fixed. This plan identifies what
can run concurrently, what must stay sequential, and how to coordinate so
parallel agents don't collide on shared files.

## Dependency Analysis

| Phase | Artifact | Hard deps | Soft deps (runtime only) |
|-------|----------|-----------|--------------------------|
| 2 Models | `models.py` | — | — |
| 3 Ingest | `ingest.py`, `docker-compose.yml`, populated Qdrant, `graph.json` | Phase 2 | — |
| 4 Retrieval | `retrieval.py` | Phase 2 | Phase 3 (Qdrant must be populated to run end-to-end, but code/tests can use a mocked client) |
| 5 FastAPI | `main.py` | Phase 4 function signatures | Phase 4 implementations |
| 6 Streamlit | `app.py` | Phase 5 endpoint contracts (already specified in the spec) | Phase 5 running |
| 7 Loom demo | recording | All of 2–6 working end-to-end | — |

Key insight: Phase 5's endpoints and Phase 6's tab structure are fully specified
in the doc, so downstream UI/API work can begin against the *spec contract*
before upstream code is implemented — as long as the upstream agents honor the
contract.

## Recommended Execution Order

### Wave 0 — sequential (blocking)
- **Phase 2 (`models.py`)**. Tiny but everything depends on the dataclass shape.
  Do not skip; do not parallelize. Also pin core deps in `pyproject.toml` here
  (pdfplumber, sentence-transformers, qdrant-client, cohere, networkx, fastapi,
  streamlit) so the parallel agents in Wave 1 don't race on the lockfile.

### Wave 1 — parallel (3 agents, isolated worktrees)
After Phase 2 lands on `main`, spawn three agents simultaneously, each in its
own worktree to avoid merge conflicts on shared files (especially
`pyproject.toml` and `docker-compose.yml`):

1. **Agent A — Phase 3 (Ingestion)**
   Owns: `ingest.py`, `docker-compose.yml`, runs the pipeline to produce a
   populated Qdrant collection + `graph.json`. End-to-end: `docker compose up -d
   && python ingest.py` produces a real, queryable index.

2. **Agent B — Phase 4 (Retrieval)**
   Owns: `retrieval.py`. Implements `search`, `rerank`, `graph_context`.
   Validates against a mock Qdrant client + a tiny fixture graph in tests so it
   does not block on Agent A. Once Agent A merges, run the same functions
   against the real index as a smoke check.

3. **Agent C — Phase 6 (Streamlit scaffolding)**
   Owns: `app.py`. Builds the three tabs (Search / Paper / Corpus) against a
   thin HTTP client that points at the FastAPI endpoint shapes from the spec.
   Use stubbed responses for local dev until Wave 2 lands.

### Wave 2 — sequential (integration)
4. **Phase 5 (`main.py`)** — wire Agent B's `retrieval.py` into the three
   endpoints (`POST /search`, `GET /papers/{id}`, `GET /graph/{id}`). Replaces
   the current hello-world stub.
5. **Connect Phase 6 to live API** — flip Agent C's HTTP client from stubs to
   `http://localhost:8000`. Smoke-test the demo flow.

### Wave 3 — handed off to user
6. **Phase 7 (Loom)** — recorded manually by the user after Waves 0–2 are
   green end-to-end. Out of scope for this plan; agents stop at Wave 2.

## Critical Files & Coordination Rules
- `models.py` — written in Wave 0, read-only for everyone after.
- `pyproject.toml` / `uv.lock` — pin all needed deps in Wave 0 to prevent Wave 1
  agents from racing on dependency adds. If a Wave 1 agent needs an
  unanticipated package, it must say so in its return summary, not silently
  edit the lockfile.
- `docker-compose.yml` — owned solely by Agent A in Wave 1.
- `main.py` — currently a hello-world stub; Wave 2 replaces it. No Wave 1 agent
  should touch it.
- Worktree isolation (`isolation: "worktree"`) for Wave 1 is recommended so the
  three agents can be merged independently after review.

## What Cannot Be Parallelized
- Phase 2 → anything. The dataclass shape is the type contract.
- Phase 5 → Phase 6 *integration* (Wave 2 step 5). Streamlit can be scaffolded
  in parallel, but pointing it at a live API has to wait for the API to exist.

## Estimated Speedup
Sequential (2→3→4→5→6) is ~5 serial units. With Wave 1 collapsing 3, 4, and 6
into one wall-clock window, the critical path becomes 2 → max(3,4,6) → 5,
roughly 3 units — about a 40% wall-clock reduction, with the caveat that
Phase 3 (ingestion + embedding compute) is likely the longest single phase and
will dominate Wave 1's duration.
