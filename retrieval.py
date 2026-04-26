"""
retrieval.py — Phase 4 (Retrieval) for the WG21 C++ papers RAG system.

Public API:
    search(query, filters, top_k)  -> list[dict]
    rerank(query, candidates, top_n) -> list[dict]
    graph_context(paper_id)        -> dict
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchText, MatchValue, Range

# ---------------------------------------------------------------------------
# Sentence-transformer singleton
# ---------------------------------------------------------------------------

_encoder = None


def _get_encoder():
    """Lazy-load the sentence-transformer model once and cache it."""
    global _encoder
    if _encoder is None:
        from sentence_transformers import SentenceTransformer
        _encoder = SentenceTransformer("all-MiniLM-L6-v2")
    return _encoder


# ---------------------------------------------------------------------------
# Qdrant client singleton
# ---------------------------------------------------------------------------

_qdrant_client = None
_COLLECTION = "wg21_papers"


def _get_qdrant() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(host="localhost", port=6333)
    return _qdrant_client


# ---------------------------------------------------------------------------
# Filter builder
# ---------------------------------------------------------------------------

def _build_filter(filters: dict) -> Filter | None:
    """Convert a user-supplied filters dict into a Qdrant Filter object."""
    if not filters:
        return None

    conditions = []

    if "status" in filters:
        conditions.append(
            FieldCondition(key="status", match=MatchValue(value=filters["status"]))
        )

    if "section_type" in filters:
        conditions.append(
            FieldCondition(
                key="section_type",
                match=MatchValue(value=filters["section_type"]),
            )
        )

    if "author" in filters:
        # Substring match against the authors field (stored as a string or list).
        # MatchText performs a case-insensitive substring search in Qdrant.
        conditions.append(
            FieldCondition(
                key="authors",
                match=MatchText(text=filters["author"]),
            )
        )

    # Date range — stored as a YYYY-MM-DD string; lexicographic comparison works.
    date_range: dict[str, Any] = {}
    if "date_from" in filters:
        date_range["gte"] = filters["date_from"]
    if "date_to" in filters:
        date_range["lte"] = filters["date_to"]
    if date_range:
        conditions.append(FieldCondition(key="date", range=Range(**date_range)))

    if not conditions:
        return None

    return Filter(must=conditions)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def search(
    query: str,
    filters: dict | None = None,
    top_k: int = 20,
) -> list[dict]:
    """Embed *query* and run a Qdrant vector search, returning up to *top_k* hits.

    Parameters
    ----------
    query:
        Free-text search string.
    filters:
        Optional dict with any subset of the keys:
        ``status``, ``section_type``, ``author``, ``date_from``, ``date_to``.
    top_k:
        Maximum number of results to return.

    Returns
    -------
    list[dict]
        Each entry contains: ``paper_id``, ``title``, ``section_type``,
        ``page_number``, ``status``, ``content``, ``score``.
    """
    qdrant = _get_qdrant()
    query_filter = _build_filter(filters or {})

    if not query.strip():
        records, _ = qdrant.scroll(
            collection_name=_COLLECTION,
            scroll_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        return [
            {
                "paper_id": (r.payload or {}).get("paper_id", ""),
                "title": (r.payload or {}).get("title", ""),
                "section_type": (r.payload or {}).get("section_type", ""),
                "page_number": (r.payload or {}).get("page_number", None),
                "status": (r.payload or {}).get("status", ""),
                "content": (r.payload or {}).get("content", ""),
                "score": 0.0,
            }
            for r in records
        ]

    encoder = _get_encoder()
    vector = encoder.encode(query).tolist()

    hits = qdrant.search(
        collection_name=_COLLECTION,
        query_vector=vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True,
    )

    return [
        {
            "paper_id": (hit.payload or {}).get("paper_id", ""),
            "title": (hit.payload or {}).get("title", ""),
            "section_type": (hit.payload or {}).get("section_type", ""),
            "page_number": (hit.payload or {}).get("page_number", None),
            "status": (hit.payload or {}).get("status", ""),
            "content": (hit.payload or {}).get("content", ""),
            "score": hit.score,
        }
        for hit in hits
    ]


# ---------------------------------------------------------------------------
# rerank
# ---------------------------------------------------------------------------

def rerank(
    query: str,
    candidates: list[dict],
    top_n: int = 5,
) -> list[dict]:
    """Re-rank *candidates* with the Cohere reranker and return the top *top_n*.

    Parameters
    ----------
    query:
        The original search query string.
    candidates:
        List of result dicts as returned by :func:`search`.
    top_n:
        Number of top results to return after reranking.

    Returns
    -------
    list[dict]
        The top *top_n* candidates sorted by ``rerank_score`` (descending).
        Each dict is augmented with a ``rerank_score`` field (float or None).
    """
    if not candidates:
        return []

    cohere_api_key = os.environ.get("COHERE_API_KEY")

    # Graceful fallback when no API key is available.
    if not cohere_api_key:
        fallback = [dict(c, rerank_score=None) for c in candidates[:top_n]]
        return fallback

    import cohere

    co = cohere.Client(cohere_api_key)

    documents = [c.get("content", "") for c in candidates]

    response = co.rerank(
        model="rerank-english-v3.0",
        query=query,
        documents=documents,
        top_n=top_n,
    )

    reranked: list[dict] = []
    for result in response.results:
        candidate = dict(candidates[result.index])
        candidate["rerank_score"] = result.relevance_score
        reranked.append(candidate)

    # Results from Cohere are already sorted by relevance_score descending.
    return reranked


# ---------------------------------------------------------------------------
# graph_context
# ---------------------------------------------------------------------------

_GRAPH_PATH = Path(__file__).parent / "graph.json"


def graph_context(paper_id: str) -> dict:
    """Return the citation neighbourhood of *paper_id* from ``graph.json``.

    Parameters
    ----------
    paper_id:
        The paper identifier, e.g. ``"P2300R7"``.

    Returns
    -------
    dict
        ``{"paper_id": ..., "cites": [...], "cited_by": [...]}``

        Each entry in ``cites`` / ``cited_by`` is
        ``{"paper_id": ..., "boundary": bool}``.

        Returns empty lists if ``graph.json`` does not exist or the node is
        absent from the graph.
    """
    empty = {"paper_id": paper_id, "cites": [], "cited_by": []}

    if not _GRAPH_PATH.exists():
        return empty

    with _GRAPH_PATH.open("r", encoding="utf-8") as fh:
        graph_data = json.load(fh)

    # graph.json is expected to be a node-link format produced by networkx:
    # {"directed": true, "nodes": [...], "links": [...]}
    # We reconstruct neighbours manually to avoid a hard networkx dependency
    # at runtime (though networkx is available if needed).
    nodes: dict[str, dict] = {}
    for node in graph_data.get("nodes", []):
        nid = node.get("id", node.get("paper_id", ""))
        if nid:
            nodes[nid] = node

    if paper_id not in nodes:
        return empty

    cites: list[dict] = []
    cited_by: list[dict] = []

    for link in graph_data.get("links", []):
        source = link.get("source", "")
        target = link.get("target", "")

        if source == paper_id:
            boundary = nodes.get(target, {}).get("boundary", target not in nodes)
            cites.append({"paper_id": target, "boundary": boundary})
        elif target == paper_id:
            boundary = nodes.get(source, {}).get("boundary", source not in nodes)
            cited_by.append({"paper_id": source, "boundary": boundary})

    return {
        "paper_id": paper_id,
        "cites": cites,
        "cited_by": cited_by,
    }
