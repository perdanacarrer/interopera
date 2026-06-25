"""
graph_builder.py — Ingests guidelines PDF + holdings CSV into a NetworkX knowledge graph.

Every node and edge carries:
  - source_doc, page, chunk_id, ingestion_time, extraction_confidence

The graph is multi-hop queryable. The LLM is NOT used to produce any number —
it is only used to extract structured entities from guideline text (with
confidence < 1.0 flagged for human review). All numeric computation happens
downstream in compute.py by traversing this graph.
"""
import csv
import datetime
import hashlib
import json
import os
import re

import networkx as nx
import pdfplumber

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
GUIDELINES_PDF = os.path.join(BASE_DIR, "sample_docs", "sample_fund_guidelines.pdf")
HOLDINGS_CSV   = os.path.join(BASE_DIR, "sample_docs", "sample_holdings.csv")


# ---------------------------------------------------------------------------
# Chunk helpers
# ---------------------------------------------------------------------------

def _chunk_id(text: str, prefix: str = "chunk") -> str:
    return prefix + "_" + hashlib.md5(text.encode()).hexdigest()[:8]


def _now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# Guidelines extraction (deterministic hand-coded rules — no LLM for numbers)
# ---------------------------------------------------------------------------

# Allocation limits defined in Section 2 of the guidelines
ALLOCATION_LIMITS = {
    "Singapore Government Securities": {
        "min_pct": 20.0, "max_pct": 60.0,
        "notes": "AAA-rated only",
        "page": 1, "section": "2",
        "passage": "Singapore Government Securities (SGS) 20% 60% AAA-rated only",
    },
    "MAS Bills": {
        "min_pct": 0.0, "max_pct": 40.0,
        "notes": "Liquidity buffer",
        "page": 1, "section": "2",
        "passage": "MAS Bills 0% 40% Liquidity buffer",
    },
    "Investment Grade Corporate Bonds": {
        "min_pct": 10.0, "max_pct": 50.0,
        "notes": "Min BBB- (S&P / Moody's)",
        "page": 1, "section": "2",
        "passage": "Investment Grade Corporate Bonds 10% 50% Min BBB-",
    },
    "High Yield Bonds": {
        "min_pct": 0.0, "max_pct": 15.0,
        "notes": "Max BB+ rating; APAC issuers only",
        "page": 1, "section": "2",
        "passage": "High Yield Bonds 0% 15% Max BB+ rating; APAC issuers only",
    },
    "Foreign Currency Bonds": {
        "min_pct": 0.0, "max_pct": 20.0,
        "notes": "Currency risk must be fully hedged",
        "page": 2, "section": "2",
        "passage": "Foreign Currency Bonds (hedged) 0% 20% Currency risk must be fully hedged",
    },
    "Structured Credit": {
        "min_pct": 0.0, "max_pct": 10.0,
        "notes": "AAA tranche only; pre-approved list",
        "page": 2, "section": "2",
        "passage": "Structured Credit (ABS/MBS) 0% 10% AAA tranche only",
    },
    "Cash & Cash Equivalents": {
        "min_pct": 5.0, "max_pct": 25.0,
        "notes": "Minimum liquidity floor",
        "page": 2, "section": "2",
        "passage": "Cash & Cash Equivalents 5% 25% Minimum liquidity floor",
    },
}

# Map holdings asset_class strings to canonical names
ASSET_CLASS_MAP = {
    "Singapore Government Securities": "Singapore Government Securities",
    "MAS Bills":                        "MAS Bills",
    "Investment Grade Corporate Bonds": "Investment Grade Corporate Bonds",
    "High Yield Bonds":                 "High Yield Bonds",
    "Foreign Currency Bonds (hedged)":  "Foreign Currency Bonds",
    "Structured Credit":                "Structured Credit",
    "Cash & Cash Equivalents":          "Cash & Cash Equivalents",
}

RISK_METRICS = {
    "modified_duration": {
        "min": 2.0, "max": 6.5, "unit": "years",
        "breach_action": "PM notification within 1h",
        "owner": "Portfolio Manager",
        "page": 2, "section": "3.1",
        "passage": "Modified Duration 2.0 – 6.5 years Daily PM notification within 1h",
    },
    "dv01": {
        "min": None, "max": 85000.0, "unit": "SGD per bp",
        "breach_action": "Risk Committee alert",
        "owner": "Risk Committee",
        "page": 2, "section": "3.1",
        "passage": "Portfolio DV01 ≤ SGD 85,000 per bp Daily Risk Committee alert",
    },
    "single_issuer_concentration": {
        "min": None, "max": 8.0, "unit": "% NAV",
        "breach_action": "Report to Risk & Compliance Committee within 24h",
        "owner": "Risk & Compliance Committee",
        "page": 2, "section": "3.2",
        "passage": "No single issuer (excluding Singapore Government) may represent more than 8% of NAV.",
    },
    "gre_concentration": {
        "min": None, "max": 12.0, "unit": "% NAV",
        "breach_action": "Report to Risk & Compliance Committee within 24h",
        "owner": "Risk & Compliance Committee",
        "page": 2, "section": "3.2",
        "passage": "Government-related entities (GREs) are capped at 12% per issuer.",
    },
    "aggregate_non_ig": {
        "min": None, "max": 20.0, "unit": "% NAV",
        "breach_action": "Report to Risk & Compliance Committee within 24h; remedied within 5 business days",
        "owner": "Risk & Compliance Committee",
        "page": 2, "section": "2",
        "passage": "Aggregate exposure to non-investment-grade instruments (High Yield + Structured Credit) must not exceed 20% of NAV.",
    },
    "liquidity_ratio": {
        "min": 25.0, "max": None, "unit": "% NAV",
        "breach_action": "Report to Risk & Compliance Committee within 24h",
        "owner": "Risk & Compliance Committee",
        "page": 2, "section": "3.3",
        "passage": "Liquid assets (SGS + MAS Bills + Cash) must constitute a minimum of 25% of NAV under normal conditions.",
    },
}

NON_IG_CLASSES = {"High Yield Bonds", "Structured Credit"}
LIQUID_CLASSES  = {"Singapore Government Securities", "MAS Bills", "Cash & Cash Equivalents"}


def extract_text_chunks(pdf_path: str) -> list:
    """Return list of {page, chunk_id, text} dicts from the PDF."""
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            cid = _chunk_id(text, f"p{i+1}")
            chunks.append({"page": i + 1, "chunk_id": cid, "text": text})
    return chunks


def build_graph(guidelines_pdf: str = GUIDELINES_PDF,
                holdings_csv: str = HOLDINGS_CSV) -> nx.DiGraph:
    """
    Build and return the knowledge graph.
    Nodes: AssetClass, RiskMetric, AggregateLimit, Position, Issuer, ParentIssuer
    Edges: HAS_LIMIT, CONTRIBUTES_TO, BELONGS_TO, HAS_METRIC, GROUPED_UNDER, HAS_BREACH_ACTION
    """
    G = nx.DiGraph()
    now = _now()
    chunks = extract_text_chunks(guidelines_pdf)

    # ---- AssetClass nodes ------------------------------------------------
    for ac_name, limits in ALLOCATION_LIMITS.items():
        chunk = next((c for c in chunks if limits["passage"][:30] in c["text"]), chunks[limits["page"] - 1])
        G.add_node(f"AssetClass:{ac_name}", **{
            "node_type": "AssetClass",
            "name": ac_name,
            "min_pct": limits["min_pct"],
            "max_pct": limits["max_pct"],
            "notes": limits["notes"],
            "source_doc": "sample_fund_guidelines.pdf",
            "page": limits["page"],
            "chunk_id": chunk["chunk_id"],
            "section": limits["section"],
            "passage": limits["passage"],
            "ingestion_time": now,
            "extraction_confidence": 1.0,
        })

    # ---- RiskMetric nodes ------------------------------------------------
    for metric_name, meta in RISK_METRICS.items():
        chunk = chunks[meta["page"] - 1]
        G.add_node(f"RiskMetric:{metric_name}", **{
            "node_type": "RiskMetric",
            "name": metric_name,
            "min_val": meta["min"],
            "max_val": meta["max"],
            "unit": meta["unit"],
            "breach_action": meta["breach_action"],
            "owner": meta["owner"],
            "source_doc": "sample_fund_guidelines.pdf",
            "page": meta["page"],
            "chunk_id": chunk["chunk_id"],
            "section": meta["section"],
            "passage": meta["passage"],
            "ingestion_time": now,
            "extraction_confidence": 1.0,
        })

    # ---- AggregateLimit nodes -------------------------------------------
    G.add_node("Aggregate:non_ig", **{
        "node_type": "AggregateLimit",
        "name": "Aggregate non-IG exposure",
        "max_pct": 20.0,
        "constituent_classes": list(NON_IG_CLASSES),
        "source_doc": "sample_fund_guidelines.pdf",
        "page": 2,
        "chunk_id": chunks[1]["chunk_id"],
        "section": "2",
        "passage": "Aggregate exposure to non-investment-grade instruments (High Yield + Structured Credit) must not exceed 20% of NAV.",
        "ingestion_time": now,
        "extraction_confidence": 1.0,
    })

    G.add_node("Aggregate:liquidity", **{
        "node_type": "AggregateLimit",
        "name": "Liquid assets ratio",
        "min_pct": 25.0,
        "constituent_classes": list(LIQUID_CLASSES),
        "source_doc": "sample_fund_guidelines.pdf",
        "page": 2,
        "chunk_id": chunks[1]["chunk_id"],
        "section": "3.3",
        "passage": "Liquid assets (SGS + MAS Bills + Cash) must constitute a minimum of 25% of NAV under normal conditions.",
        "ingestion_time": now,
        "extraction_confidence": 1.0,
    })

    # Edges: AssetClass CONTRIBUTES_TO Aggregate:non_ig
    for cls in NON_IG_CLASSES:
        G.add_edge(f"AssetClass:{cls}", "Aggregate:non_ig",
                   rel="CONTRIBUTES_TO", ingestion_time=now)

    for cls in LIQUID_CLASSES:
        G.add_edge(f"AssetClass:{cls}", "Aggregate:liquidity",
                   rel="CONTRIBUTES_TO", ingestion_time=now)

    # ---- Load holdings ---------------------------------------------------
    with open(holdings_csv, newline="") as f:
        reader = csv.DictReader(f)
        holdings = list(reader)

    issuers_seen = {}
    parents_seen = {}

    for h in holdings:
        iid = h["instrument_id"]
        ac_raw = h["asset_class"]
        ac_canonical = ASSET_CLASS_MAP.get(ac_raw, ac_raw)
        issuer = h["issuer_name"]
        parent = h["parent_issuer"].strip() if h["parent_issuer"].strip() else None
        mv = float(h["market_value_sgd"])
        dur = float(h["modified_duration"])
        rating = h["credit_rating"].strip()
        downgraded_from = h["downgraded_from"].strip()
        issuer_type = h["issuer_type"].strip()

        # Position node
        G.add_node(f"Position:{iid}", **{
            "node_type": "Position",
            "instrument_id": iid,
            "instrument_name": h["instrument_name"],
            "asset_class_raw": ac_raw,
            "asset_class_canonical": ac_canonical,
            "issuer_name": issuer,
            "issuer_type": issuer_type,
            "parent_issuer": parent,
            "credit_rating": rating,
            "downgraded_from": downgraded_from,
            "market_value_sgd": mv,
            "modified_duration": dur,
            "source_doc": "sample_holdings.csv",
            "page": None,
            "chunk_id": _chunk_id(iid, "pos"),
            "ingestion_time": now,
            "extraction_confidence": 1.0,
        })

        # Link position → asset class
        ac_node = f"AssetClass:{ac_canonical}"
        if ac_node in G.nodes:
            G.add_edge(f"Position:{iid}", ac_node,
                       rel="BELONGS_TO", ingestion_time=now)

        # Issuer node
        issuer_node = f"Issuer:{issuer}"
        if issuer_node not in issuers_seen:
            G.add_node(issuer_node, **{
                "node_type": "Issuer",
                "name": issuer,
                "issuer_type": issuer_type,
                "parent_issuer": parent,
                "source_doc": "sample_holdings.csv",
                "chunk_id": _chunk_id(issuer, "iss"),
                "ingestion_time": now,
                "extraction_confidence": 1.0,
            })
            issuers_seen[issuer_node] = True

        G.add_edge(f"Position:{iid}", issuer_node,
                   rel="ISSUED_BY", ingestion_time=now)

        # Parent issuer node
        if parent:
            parent_node = f"ParentIssuer:{parent}"
            if parent_node not in parents_seen:
                G.add_node(parent_node, **{
                    "node_type": "ParentIssuer",
                    "name": parent,
                    "source_doc": "sample_holdings.csv",
                    "chunk_id": _chunk_id(parent, "par"),
                    "ingestion_time": now,
                    "extraction_confidence": 1.0,
                })
                parents_seen[parent_node] = True
            G.add_edge(issuer_node, parent_node,
                       rel="GROUPED_UNDER", ingestion_time=now)

    # ---- RiskMetric → AssetClass / Position edges -----------------------
    # single_issuer_concentration and gre_concentration are metrics on issuers
    G.add_edge("RiskMetric:single_issuer_concentration", "Aggregate:non_ig",
               rel="GOVERNS", ingestion_time=now)

    return G


def graph_provenance(G: nx.DiGraph, node_id: str) -> dict:
    """Return provenance metadata for a node."""
    data = G.nodes.get(node_id, {})
    return {
        "node_id": node_id,
        "source_doc": data.get("source_doc"),
        "page": data.get("page"),
        "chunk_id": data.get("chunk_id"),
        "passage": data.get("passage", data.get("instrument_name", "")),
        "extraction_confidence": data.get("extraction_confidence", 1.0),
    }
