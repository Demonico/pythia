from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import retrieval

app = FastAPI(title="WG21 RAG API")

_GRAPH_PATH = Path(__file__).parent / "graph.json"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SearchFilters(BaseModel):
    status: str | None = None
    section_type: str | None = None
    author: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class SearchRequest(BaseModel):
    query: str
    filters: SearchFilters | None = None
    top_n: int = 5


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/search")
def search(req: SearchRequest) -> list[dict[str, Any]]:
    filters: dict[str, str] = {}
    if req.filters:
        for key in ("status", "section_type", "author", "date_from", "date_to"):
            val = getattr(req.filters, key, None)
            if val:
                filters[key] = val

    candidates = retrieval.search(req.query, filters or None, top_k=20)
    return retrieval.rerank(req.query, candidates, top_n=req.top_n)


@app.get("/papers/{paper_id}")
def get_paper(paper_id: str) -> dict[str, Any]:
    if not _GRAPH_PATH.exists():
        raise HTTPException(status_code=503, detail="Index not built yet — run ingest.py first")

    with _GRAPH_PATH.open() as f:
        graph_data = json.load(f)

    nodes = {n.get("id", n.get("paper_id", "")): n for n in graph_data.get("nodes", [])}
    pid = paper_id.upper()
    node = nodes.get(pid)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Paper '{paper_id}' not found")

    ctx = retrieval.graph_context(pid)
    return {
        "paper_id": pid,
        "title": node.get("title", ""),
        "authors": node.get("authors", []),
        "date": node.get("date", ""),
        "status": node.get("status", ""),
        "cites": [e["paper_id"] for e in ctx["cites"]],
        "cited_by": [e["paper_id"] for e in ctx["cited_by"]],
    }


@app.get("/graph/{paper_id}")
def get_graph(paper_id: str) -> dict[str, Any]:
    ctx = retrieval.graph_context(paper_id.upper())
    if not ctx["cites"] and not ctx["cited_by"]:
        if not _GRAPH_PATH.exists():
            raise HTTPException(status_code=503, detail="Index not built yet — run ingest.py first")
    return ctx


@app.get("/corpus")
def get_corpus() -> list[dict[str, Any]]:
    if not _GRAPH_PATH.exists():
        return []

    with _GRAPH_PATH.open() as f:
        graph_data = json.load(f)

    corpus = []
    for node in graph_data.get("nodes", []):
        if node.get("boundary"):
            continue
        corpus.append({
            "paper_id": node.get("id", node.get("paper_id", "")),
            "title": node.get("title", ""),
            "authors": node.get("authors", []),
            "date": node.get("date", ""),
            "status": node.get("status", ""),
        })
    return corpus
