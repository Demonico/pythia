# Dev Log — Pythia

A running log of development sessions, written to support future articles about this project.

---

## Pre-Recording Bug Sweep: Six Fixes Before the Camera Rolls
*Monday April 27, 2026, 09:38*

### What We Built
Fixed six bugs found while prepping to record a demo of Pythia — broken citation display, negative search scores, malformed titles and authors in the corpus, garbled PDF artifacts in author fields, and status classification that never worked. The app went from visibly rough to demo-ready.

### How It Came Together
All six issues were planned one at a time before any code was written. Each fix was walked through conversationally — root cause, proposed solution, tradeoffs — and confirmed before moving to the next. The fixes split across three layers: `ingest.py` for metadata parsing (titles, authors, status), `retrieval.py` and `main.py` for citation lookup, and `app.py` for score display.

The metadata fixes were the bulk of the work and required the most iteration. The title heuristic originally rejected lines that *were* a bare paper ID but not lines that *contained* one, so "Document Number: N4685" slipped through and became the title. Switching `.match()` to `.search()` fixed that but exposed the next failure — "Date: 2017-07-31" was now the first valid line. This led to a growing exclusion filter: date lines, metadata field labels, email-containing lines, bullet points. Author parsing had a similar cascade: the label search covered all three front-matter pages, so it would match "author" mid-sentence in the body and return "regrets not proposing this in the C++20 design space." as an author name. Restricting to page 1 with `re.MULTILINE` fixed it.

The citation bug turned out to be one word wrong. NetworkX changed its serialization key from `"links"` to `"edges"` in a newer version. `graph_context()` called `graph_data.get("links", [])`, which silently returned empty every time. 466 edges in the file, zero ever seen. One string changed, done.

### The Interesting Parts
The score normalization has a proper reason behind it: `cross-encoder/ms-marco-MiniLM-L-6-v2` outputs raw logits, and sigmoid is the mathematically correct inverse — it's what the model's final layer undoes. `1 / (1 + exp(-raw))` isn't cosmetic clamping, it preserves ordering and produces values that mean something.

The planning phase repeatedly got stuck reading `graph.json` when it wasn't necessary for planning purposes. And despite the plan explicitly deferring ingest to the end, the script got run several times mid-session to check intermediate output — each run taking several minutes. The instinct to verify immediately after each change is hard to suppress, but for a slow script the right discipline is: make all the changes, then run once.

### What's Next
A handful of titles are still imperfect — P0896R4 picks up "Casey Carter", P0939R4 shows "IRECTION FOR" (a pdfplumber fragment of an all-caps heading). These are genuine PDF extraction limits for papers without a clean title line on page 1. Good enough to record; a proper fix would require structured front-matter parsing or a lookup against the WG21 paper index.

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
