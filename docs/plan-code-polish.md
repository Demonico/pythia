# Code Polish Plan

Items identified during a post-demo code review. The code is functional and has been linted
with ruff; these are type-safety, API-design, and consistency improvements only.

Grouped by priority so they can be tackled incrementally.

---

## P0 — Bugs that would surface during the demo

### 1. `app.py:235` — Python 3 syntax error in `except` clause

```python
# current (Python 2 syntax — SyntaxError if this branch ever executes)
except requests.exceptions.ConnectionError, requests.exceptions.Timeout:

# fix
except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
```

The Corpus tab will crash if the API is down when a viewer tries it.

### 2. `ingest.py:85` — `parse_pdf` return type and docstring mismatch

The annotation says `-> tuple[list[str], dict]` and the docstring mentions `raw_meta`, but
the function only returns `list[str]`. Leftover from an earlier refactor.

```python
# fix signature and docstring
def parse_pdf(pdf_path: Path) -> list[str]:
    """Return one string per page (pages[i] = page i+1 text)."""
```

### 3. `ingest.py:319` — `build_graph` return type wrong

Annotated `-> nx.DiGraph` but returns `G, boundary_nodes`.

```python
# fix
def build_graph(papers: list[Paper], corpus_ids: set[str]) -> tuple[nx.DiGraph, set[str]]:
```

---

## P1 — Type safety

### 4. `models.py` — Use `Literal` for constrained string fields

`Section.section_type` and `Paper.status` accept only a fixed vocabulary but are typed as
bare `str`. Replace with `Literal` so type-checkers and callers know the valid values.

```python
from typing import Literal

SectionType = Literal["abstract", "motivation", "introduction", "proposal", "wording", "discussion", "other"]
StatusType  = Literal["accepted", "rejected", "pending"]
```

### 5. `retrieval.py:23-24,50` — Annotate singleton globals

The lazy-loaded singletons are inferred as `None` by type-checkers.

```python
_encoder: "SentenceTransformer | None" = None
_cross_encoder: "CrossEncoder | None" = None
_qdrant_client: QdrantClient | None = None
```

### 6. `retrieval.py:27,37` — Add return annotations to lazy loaders

`_get_encoder` and `_get_cross_encoder` have no `->` annotation. Use quoted strings
(imports are inside the function) or `-> Any`.

### 7. `retrieval.py:66`, `ingest.py:95` — Tighten bare `dict` annotations

- `_build_filter(filters: dict)` → `filters: dict[str, Any]`
- `extract_metadata(...) -> dict` → `-> dict[str, Any]`
- `rerank(...) -> list[dict]` → `-> list[dict[str, Any]]`

---

## P2 — Architecture / DRY

### 8. Extract shared constants to `config.py`

Three values are duplicated across files:

| Constant | Defined in |
|---|---|
| `"wg21_papers"` (collection name) | `ingest.py`, `retrieval.py` |
| `graph.json` path | `retrieval.py`, `main.py` |
| `"all-MiniLM-L6-v2"` (model name) | `ingest.py`, `retrieval.py` |

Move all three to a single `config.py`; import from there everywhere.

### 9. Centralize `graph.json` parsing in `retrieval.py`

`graph.json` is opened and parsed independently in three places:
- `retrieval.graph_context`
- `main.get_paper` (re-implements node lookup, then calls `graph_context` for citations)
- `main.get_corpus`

Add a `load_graph_nodes() -> dict[str, dict]` helper to `retrieval.py` and have
`get_paper` and `get_corpus` call it instead of re-parsing.

### 10. `main.py` — Replace `getattr` loop with `model_dump`

The filter-building loop (lines 44-48) uses dynamic attribute access on a Pydantic model:

```python
# current
for key in ("status", "section_type", "author", "date_from", "date_to"):
    val = getattr(req.filters, key, None)
    if val:
        filters[key] = val

# idiomatic
filters = req.filters.model_dump(exclude_none=True) if req.filters else {}
```

---

## P3 — Pythonic patterns

### 11. `ingest.py` — Move regex compilation out of `extract_metadata`

Three patterns are compiled inside `extract_metadata` on every call:
- `_META_FIELD_RE` (line 106)
- `_CURLY_QUOTE_RE` (line 137)
- `_NAME_RE` (line 153)

Move them to module level alongside the existing `_PAPER_ID_RE` and `_DATE_RE`.

### 12. `ingest.py:67` — Remove no-op `.replace`

```python
# current — .replace("R", "R") does nothing after .upper()
return m.group(1).upper().replace("R", "R")

# fix
return m.group(1).upper()
```

### 13. `app.py` — Extract API call helper

The `try/except → result = None` pattern for `requests` calls is repeated three times.
A small helper removes the duplication:

```python
def _api_get(url: str, timeout: int = 15) -> dict | list | None:
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error("Could not connect to the API. Is it running?")
    except requests.exceptions.HTTPError as exc:
        st.error(f"API error: {exc}")
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")
    return None
```

### 14. `app.py` — Move sigmoid normalization out of the display layer

`score = 1 / (1 + math.exp(-raw))` (line 103) is applied to raw CrossEncoder logits inside
the UI render loop. It belongs in `retrieval.rerank` so all callers get normalized scores
and `app.py` doesn't need `import math`.

---

## P4 — Docstrings

All items here are missing docstrings (PEP 257). One-liners are sufficient for private
helpers; public functions should describe parameters and return value.

| Location | Missing on |
|---|---|
| `models.py` | module, `Section` class, `Paper` class |
| `ingest.py` | `_classify_status`, `_classify_section_type`, `extract_citations`, `setup_qdrant`, `embed_and_store`, `_point_id` |
| `retrieval.py` | `rerank` (the only public function without one) |
| `main.py` | module |
| `app.py` | module |

Also: `ingest.py` uses plain one-liners while `retrieval.py` uses NumPy style. Pick one
and apply consistently.
