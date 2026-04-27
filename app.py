import math
import os
import requests
import streamlit as st

st.set_page_config(page_title="WG21 RAG", layout="wide")

st.markdown(
    """
<style>
[data-testid="stAppDeployButton"] {display: none;}
</style>
""",
    unsafe_allow_html=True,
)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Sidebar filters (used by Search tab)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Search Filters")
    filter_status = st.selectbox(
        "Status",
        options=["", "accepted", "rejected", "pending"],
        key="filter_status",
    )
    filter_section_type = st.selectbox(
        "Section type",
        options=[
            "",
            "motivation",
            "proposal",
            "wording",
            "discussion",
            "introduction",
            "abstract",
            "other",
        ],
        key="filter_section_type",
    )
    filter_author = st.text_input("Author", key="filter_author")
    filter_date_from = st.date_input("Date from", value=None, key="filter_date_from")
    filter_date_to = st.date_input("Date to", value=None, key="filter_date_to")
    top_n = st.number_input(
        "Top N", min_value=1, max_value=20, value=5, step=1, key="top_n"
    )

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_search, tab_paper, tab_corpus = st.tabs(["Search", "Paper", "Corpus"])

# ---------------------------------------------------------------------------
# Search Tab
# ---------------------------------------------------------------------------
with tab_search:
    st.header("Search")
    query = st.text_input("Query", key="search_query")

    if st.button("Search", key="btn_search"):
        filters = {}
        if filter_status:
            filters["status"] = filter_status
        if filter_section_type:
            filters["section_type"] = filter_section_type
        if filter_author.strip():
            filters["author"] = filter_author.strip()
        if filter_date_from:
            filters["date_from"] = filter_date_from.isoformat()
        if filter_date_to:
            filters["date_to"] = filter_date_to.isoformat()

        payload = {
            "query": query,
            "filters": filters,
            "top_n": int(top_n),
        }

        try:
            response = requests.post(f"{API_BASE_URL}/search", json=payload, timeout=30)
            response.raise_for_status()
            results = response.json()
        except requests.exceptions.ConnectionError:
            st.error("Could not connect to the API. Is it running?")
            results = None
        except requests.exceptions.HTTPError as exc:
            st.error(f"API error: {exc}")
            results = None
        except Exception as exc:
            st.error(f"Unexpected error: {exc}")
            results = None

        if results is not None:
            if not results:
                st.info("No results found.")
            else:
                for item in results:
                    paper_id = item.get("paper_id", "")
                    section_type = item.get("section_type", "")
                    raw = item.get("rerank_score") or item.get("score", 0.0)
                    score = 1 / (1 + math.exp(-raw))
                    label = f"{paper_id} — {section_type} (score: {score:.3f})"
                    with st.expander(label):
                        st.write(f"**Title:** {item.get('title', '')}")
                        st.write(f"**Status:** {item.get('status', '')}")
                        st.write(f"**Page:** {item.get('page_number', '')}")
                        st.write("**Content:**")
                        st.write(item.get("content", ""))

# ---------------------------------------------------------------------------
# Paper Tab
# ---------------------------------------------------------------------------
with tab_paper:
    st.header("Paper Lookup")
    paper_id_input = st.text_input("Paper ID (e.g. P2300R7)", key="paper_id_input")

    if st.button("Load", key="btn_load"):
        pid = paper_id_input.strip()
        if not pid:
            st.warning("Please enter a Paper ID.")
        else:
            # Fetch metadata
            try:
                meta_resp = requests.get(f"{API_BASE_URL}/papers/{pid}", timeout=15)
                if meta_resp.status_code == 404:
                    st.error(f"Paper '{pid}' not found.")
                    meta_resp = None
                else:
                    meta_resp.raise_for_status()
            except requests.exceptions.ConnectionError:
                st.error("Could not connect to the API. Is it running?")
                meta_resp = None
            except requests.exceptions.HTTPError as exc:
                st.error(f"API error: {exc}")
                meta_resp = None
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")
                meta_resp = None

            if meta_resp is not None:
                meta = meta_resp.json()
                st.subheader("Metadata")
                st.write(f"**Title:** {meta.get('title', '')}")
                authors = meta.get("authors", [])
                st.write(f"**Authors:** {', '.join(authors)}")
                st.write(f"**Date:** {meta.get('date', '')}")
                st.write(f"**Status:** {meta.get('status', '')}")

                # Fetch graph
                try:
                    graph_resp = requests.get(f"{API_BASE_URL}/graph/{pid}", timeout=15)
                    if graph_resp.status_code == 404:
                        st.error(f"Graph for '{pid}' not found.")
                        graph_resp = None
                    else:
                        graph_resp.raise_for_status()
                except requests.exceptions.ConnectionError:
                    st.error("Could not connect to the API for graph data.")
                    graph_resp = None
                except requests.exceptions.HTTPError as exc:
                    st.error(f"API error fetching graph: {exc}")
                    graph_resp = None
                except Exception as exc:
                    st.error(f"Unexpected error fetching graph: {exc}")
                    graph_resp = None

                if graph_resp is not None:
                    graph = graph_resp.json()
                    st.subheader("Citations")

                    rows = []
                    for entry in graph.get("cites", []):
                        rows.append(
                            {
                                "Relationship": "cites",
                                "Paper ID": entry.get("paper_id", ""),
                                "Boundary": entry.get("boundary", False),
                            }
                        )
                    for entry in graph.get("cited_by", []):
                        rows.append(
                            {
                                "Relationship": "cited_by",
                                "Paper ID": entry.get("paper_id", ""),
                                "Boundary": entry.get("boundary", False),
                            }
                        )

                    if not rows:
                        st.info("No citation data available.")
                    else:
                        # Render as markdown table with red highlighting for boundary nodes
                        header = "| Relationship | Paper ID | Boundary |\n|---|---|---|"
                        table_lines = [header]
                        for row in rows:
                            rel = row["Relationship"]
                            p = row["Paper ID"]
                            boundary = row["Boundary"]
                            if boundary:
                                paper_cell = f'<span style="color:red">{p}</span>'
                                boundary_cell = "Yes"
                            else:
                                paper_cell = p
                                boundary_cell = "No"
                            table_lines.append(
                                f"| {rel} | {paper_cell} | {boundary_cell} |"
                            )
                        st.markdown("\n".join(table_lines), unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Corpus Tab
# ---------------------------------------------------------------------------
with tab_corpus:
    st.header("Corpus")
    try:
        corpus_resp = requests.get(f"{API_BASE_URL}/corpus", timeout=15)
        corpus_resp.raise_for_status()
        corpus = corpus_resp.json()
        if not corpus:
            st.info("Corpus is empty.")
        else:
            rows = [
                {
                    "Paper ID": item.get("paper_id", ""),
                    "Title": item.get("title", ""),
                    "Authors": ", ".join(item.get("authors", [])),
                    "Date": item.get("date", ""),
                    "Status": item.get("status", ""),
                }
                for item in corpus
            ]
            st.dataframe(rows, use_container_width=True)
    except requests.exceptions.ConnectionError, requests.exceptions.Timeout:
        st.warning("Corpus not available — is the API running?")
    except Exception as exc:
        st.warning(f"Corpus not available — is the API running? ({exc})")
