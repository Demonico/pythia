# Replace Cohere Reranker with sentence-transformers CrossEncoder

## Context
The current `rerank()` function in `retrieval.py` calls the Cohere API
(`rerank-english-v3.0`), which requires a `COHERE_API_KEY` environment variable.
Without the key it silently falls back to returning candidates unranked.
`sentence-transformers` (already a project dependency) ships a `CrossEncoder`
class that does the same job locally with no API key, no network call, and
comparable quality on technical text.

Goal: replace the Cohere call with a `CrossEncoder` singleton, remove the
`cohere` package from dependencies, and keep the same public interface.

---

## What Changes

### `retrieval.py`
- Add a `_cross_encoder` module-level singleton and a `_get_cross_encoder()`
  lazy-loader, mirroring the existing `_get_encoder()` pattern for the
  bi-encoder.
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` — small, fast, strong on
  passage reranking.
- Rewrite `rerank()`:
  1. Build a list of `[query, content]` pairs from candidates
  2. Call `model.predict(pairs)` to get a float score per pair
  3. Sort candidates by score descending, take top_n
  4. Return each candidate dict augmented with `rerank_score: float`
- Remove the `COHERE_API_KEY` env-var check and the `import cohere` block
  entirely — reranking now always runs.

### `pyproject.toml`
- Remove `"cohere>=5.0.0"` from dependencies.

### Nothing else changes
- `main.py` calls `retrieval.rerank()` — interface unchanged.
- `app.py` reads `rerank_score` from results — interface unchanged.
- `ingest.py`, `models.py`, `docker-compose.yml` — untouched.

---

## Verification
1. `uv sync` — cohere uninstalled, no new packages needed (CrossEncoder is in
   sentence-transformers)
2. Start the API: `uvicorn main:app --reload`
3. POST to `/search` with a query — results should have `rerank_score` as a
   float (not `null`) without any `COHERE_API_KEY` set
4. Confirm cohere is gone: `uv run python -c "import cohere"` should fail with
   ModuleNotFoundError
