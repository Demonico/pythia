# Dev Log — Pythia

A running log of development sessions, written to support future articles about this project.

---

## First Run, Runtime Surprises, and Polish
*Sunday April 26, 2026, 6:01 PM*

### What We Built
Got the stack running for the first time, fixed two runtime errors that only surfaced when actually using the app, cleaned up the Streamlit UI, replaced pylint with ruff, and rewrote the README from scratch.

### How It Came Together
The first real search query immediately hit a `'QdrantClient' object has no attribute 'search'` error — qdrant-client 1.9+ removed the `search` method in favour of `query_points`. One-line fix. The second issue was more of a UX gap: the search tab required a query string, which meant you couldn't browse by filter alone. Fixed by falling back to a Qdrant `scroll` when the query is blank, which pages through the collection with filters applied but no vector search.

Pylint was causing problems and got swapped for ruff. One genuine issue was caught (unused import in `ingest.py`); the E402 warnings for imports-after-sys.path are intentional and suppressed per-file.

The README went through several rounds — the first version was too technical up front, with commands before explanations. Rewrote it so every section leads with context before showing anything to run.

### The Interesting Parts
Streamlit's deploy button has no clean removal path. `toolbarMode = "minimal"` in config.toml removes it without a flash, but also kills the hamburger menu. The only way to remove just the deploy button is CSS injection via `st.markdown`, which causes a visible flash because the button renders before the styles apply. For a demo, the flash is the less-bad tradeoff — the hamburger menu is useful enough to keep.

The name Pythia came up — named after the Oracle of Delphi, which is now in the README intro. Ask a question, get meaning back rather than facts. It fits.

### What's Next
Haven't recorded the Loom demo yet. That's the remaining piece.

---

## Building a WG21 C++ Papers RAG Service in Parallel
*Sunday April 26, 2026, 4:48 PM*

### What We Built
A full RAG pipeline for searching ISO C++ proposals: a PDF ingestion script that parses, chunks, embeds, and indexes 20 papers into Qdrant; a retrieval module with vector search, Cohere reranking, and citation graph traversal; a FastAPI backend with four endpoints; and a three-tab Streamlit UI. The project went from a hello-world FastAPI stub to a working end-to-end system in a single session.

### How It Came Together
The session started with a parallelization question — the spec was written as six sequential phases, but we mapped out the dependency graph and identified that phases 3 (ingestion), 4 (retrieval), and 6 (Streamlit) had no hard dependencies on each other once phase 2 (the data models) was locked in. Parallelizing is the default approach here, so once the models and dependency pins landed on main, three sub-agents were launched simultaneously in isolated git worktrees. Each agent owned exactly one file: `ingest.py`, `retrieval.py`, and `app.py`. Phase 5 — the FastAPI wiring in `main.py` — came after, once the retrieval function signatures existed to import.

### The Interesting Parts
Two bugs were caught during the merge review rather than at runtime. First, `retrieval.py` had the wrong path for `graph.json` — it used `.parent.parent` which would have resolved one directory above the project root. Second, the boundary node detection was silently broken: it checked `target not in nodes` to decide if a citation was a boundary node, but boundary nodes *are* added to the graph (with `boundary=True`), so the check always returned False. Both would have produced wrong output without any errors.

A third issue surfaced when writing the API: the graph nodes only stored `boundary=True/False`, so the `/corpus` and `/papers/{id}` endpoints had no metadata to serve. The fix was to store `title`, `authors`, `date`, and `status` on each node at build time — obvious in hindsight, but easy to miss when ingestion and the API are written by different agents in parallel.

The worktree approach also left stale git branch references that showed up in PyCharm's visualization. Worth noting for future sessions using sub-agents: prune worktrees immediately after merging their output, not as an afterthought. `git worktree prune` cleans it up, but it's noise that shouldn't appear at all.

### What's Next
The stack is ready to run — `uv sync`, `docker compose up -d`, `python ingest.py`, then the API and UI. The main unknowns are chunk quality (WG21 papers aren't consistently formatted, so the section-header heuristics may produce uneven results) and retrieval quality overall. Both will surface through actual use rather than speculation. Cohere reranking is wired in but optional — if no API key is set, results fall back to raw vector score order.

---
