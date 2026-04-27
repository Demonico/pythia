# Pre-recording bug fixes

Six bugs found during pre-recording prep. All are rooted in the ingestion pipeline (`ingest.py`) except the score display issue (frontend/retrieval) and the citation display bug (frontend gate logic). Fixing issues 1 and 3–6 all require re-running `ingest.py` to regenerate `graph.json`; fix them together in one re-ingestion pass.

---

## Issue 1 — Citation data shows "No citation data available"

**Root cause:** `graph.json` has 466 edges and all corpus papers are present as nodes — the data exists. The graph fetch runs and returns data — but `rows` is still empty. The remaining suspect is that `graph_resp.json()` returns `{"cites": [], "cited_by": []}` because the lookup at `retrieval.py:247` (`if paper_id not in nodes`) fails silently. The node dict is built with `node.get("id", node.get("paper_id", ""))` — likely a trailing whitespace or encoding issue in the keys.

**Fix:**
- `retrieval.py:244` — add `.strip()` to `nid` when building the `nodes` dict
- `main.py:80` — strip and uppercase the incoming `paper_id` before passing to `graph_context`

**Files:** `retrieval.py:241-245`, `main.py:80`

---

## Issue 2 — Search scores are negative

**Root cause:** `cross-encoder/ms-marco-MiniLM-L-6-v2` outputs raw logits (unbounded, routinely negative). These land in `rerank_score` at `retrieval.py:200` and are displayed as-is via `app.py:87-88`.

**Fix:** Apply sigmoid normalization in `app.py:87` before display:
```python
import math
raw = item.get("rerank_score") or item.get("score", 0.0)
score = 1 / (1 + math.exp(-raw))
```

**Files:** `app.py:87-88`

---

## Issue 3 — Titles show "Document Number: PXXXX"

**Root cause:** Title heuristic at `ingest.py:106` uses `_PAPER_ID_RE.match()` which only rejects lines that _are_ a bare paper ID, not lines that _contain_ one. "Document Number: N4685" passes the test.

**Fix:**
1. Change `not _PAPER_ID_RE.match(line)` → `not _PAPER_ID_RE.search(line)`
2. Add pre-filter skipping lines matching `r"(?i)^doc(?:ument)?(?:\s*no\.?|ument\s+number|\s*#)\s*[:\-]?"`

**Files:** `ingest.py:106`

---

## Issue 4 — Authors field empty on many papers

**Root cause:** `ingest.py:112-113` requires an explicit `Authors:/Editor:` label with names on the same line. Most WG21 papers list authors vertically with no label.

**Fix:** Add a fallback name-cluster scan after the label match fails:
```python
if not authors:
    name_re = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+")
    candidates = [l.strip() for l in front.splitlines() if name_re.match(l.strip())]
    authors = candidates[:6] if len(candidates) >= 2 else []
```

**Files:** `ingest.py:110-122`

**Note:** Review output after re-ingestion — name-cluster heuristic can produce false positives.

---

## Issue 5 — P2502R2 authors field garbled

**Root cause:** pdfplumber extracts a PDF color-change annotation as a text run that lands in the authors field. Short fragments pass the 80-char filter.

**Fix:** Add rejection filters in `ingest.py:118-122` for fragments that:
- Contain Unicode curly quotes (`“`, `”`, `‘`, `’`)
- Contain color keywords: `re.search(r"(?i)(blue|magenta|red|green|color)", a)`
- Are run-on lowercase strings: `re.search(r"[a-z]{12,}", a)`

**Files:** `ingest.py:118-122`

---

## Issue 6 — All statuses are "pending"

**Root cause:** `_classify_status()` at `ingest.py:76-82` checks for "accepted"/"rejected" — words WG21 papers don't use.

**Fix:**
```python
def _classify_status(first_page_text: str) -> str:
    lower = first_page_text.lower()
    if any(k in lower for k in ("adopted", "incorporated into", "merged into")):
        return "accepted"
    if any(k in lower for k in ("not adopted", "withdrawn", "rejected")):
        return "rejected"
    return "pending"
```

**Files:** `ingest.py:76-82`

---

## Execution order

1. Fix `ingest.py` (issues 3, 4, 5, 6) — all metadata parsing fixes
2. Fix `retrieval.py` + `main.py` (issue 1) — citation lookup fix
3. Fix `app.py` (issue 2) — score display fix
4. Re-run `ingest.py` to regenerate `graph.json` and Qdrant vectors
5. Smoke-test: check P2444R0, N4775, P0057R8 in Paper tab for citations; verify scores are 0–1; verify titles/authors/status in Corpus tab

---

## Files to modify

| File | Issues |
|------|--------|
| `ingest.py` | 3, 4, 5, 6 |
| `retrieval.py` | 1 |
| `main.py` | 1 |
| `app.py` | 2 |
