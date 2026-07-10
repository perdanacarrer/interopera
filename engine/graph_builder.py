"""
graph_builder.py — Ingests guidelines PDF + holdings CSV into a NetworkX knowledge graph.
Every node/edge carries: source_doc, page, chunk_id, ingestion_time, extraction_confidence.
The LLM is NOT used here — all extraction is deterministic rule tables.
"""
import csv, datetime, hashlib, os
import networkx as nx
import pdfplumber

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
GUIDELINES_PDF = os.path.join(BASE_DIR, "sample_docs", "sample_fund_guidelines.pdf")
HOLDINGS_CSV   = os.path.join(BASE_DIR, "sample_docs", "sample_holdings.csv")

def _chunk_id(text, prefix="chunk"):
    return prefix + "_" + hashlib.md5(text.encode()).hexdigest()[:8]

def _now():
    return datetime.datetime.utcnow().isoformat() + "Z"

ALLOCATION_LIMITS = {
    "Singapore Government Securities":   {"min_pct":20.0,"max_pct":60.0,"notes":"AAA-rated only","page":1,"section":"2","passage":"Singapore Government Securities (SGS) 20% 60% AAA-rated only"},
    "MAS Bills":                         {"min_pct":0.0,"max_pct":40.0,"notes":"Liquidity buffer","page":1,"section":"2","passage":"MAS Bills 0% 40% Liquidity buffer"},
    "Investment Grade Corporate Bonds":  {"min_pct":10.0,"max_pct":50.0,"notes":"Min BBB-","page":1,"section":"2","passage":"Investment Grade Corporate Bonds 10% 50% Min BBB-"},
    "High Yield Bonds":                  {"min_pct":0.0,"max_pct":15.0,"notes":"Max BB+; APAC only","page":1,"section":"2","passage":"High Yield Bonds 0% 15% Max BB+ rating; APAC issuers only"},
    "Foreign Currency Bonds":            {"min_pct":0.0,"max_pct":20.0,"notes":"Must be fully hedged","page":2,"section":"2","passage":"Foreign Currency Bonds (hedged) 0% 20% Currency risk must be fully hedged"},
    "Structured Credit":                 {"min_pct":0.0,"max_pct":10.0,"notes":"AAA tranche only","page":2,"section":"2","passage":"Structured Credit (ABS/MBS) 0% 10% AAA tranche only"},
    "Cash & Cash Equivalents":           {"min_pct":5.0,"max_pct":25.0,"notes":"Minimum liquidity floor","page":2,"section":"2","passage":"Cash & Cash Equivalents 5% 25% Minimum liquidity floor"},
}

ASSET_CLASS_MAP = {
    "Singapore Government Securities":   "Singapore Government Securities",
    "MAS Bills":                         "MAS Bills",
    "Investment Grade Corporate Bonds":  "Investment Grade Corporate Bonds",
    "High Yield Bonds":                  "High Yield Bonds",
    "Foreign Currency Bonds (hedged)":   "Foreign Currency Bonds",
    "Structured Credit":                 "Structured Credit",
    "Cash & Cash Equivalents":           "Cash & Cash Equivalents",
}

RISK_METRICS = {
    "modified_duration":           {"min":2.0,"max":6.5,"unit":"years","breach_action":"PM notification within 1h","owner":"Portfolio Manager","page":2,"section":"3.1","passage":"Modified Duration 2.0 – 6.5 years Daily PM notification within 1h"},
    "dv01":                        {"min":None,"max":85000.0,"unit":"SGD per bp","breach_action":"Risk Committee alert","owner":"Risk Committee","page":2,"section":"3.1","passage":"Portfolio DV01 ≤ SGD 85,000 per bp Daily Risk Committee alert"},
    "single_issuer_concentration": {"min":None,"max":8.0,"unit":"% NAV","breach_action":"Report to Risk & Compliance Committee within 24h","owner":"Risk & Compliance Committee","page":2,"section":"3.2","passage":"No single issuer (excluding Singapore Government) may represent more than 8% of NAV."},
    "gre_concentration":           {"min":None,"max":12.0,"unit":"% NAV","breach_action":"Report to Risk & Compliance Committee within 24h","owner":"Risk & Compliance Committee","page":2,"section":"3.2","passage":"Government-related entities (GREs) are capped at 12% per issuer."},
    "aggregate_non_ig":            {"min":None,"max":20.0,"unit":"% NAV","breach_action":"Report to Risk & Compliance Committee within 24h; remedied within 5 business days","owner":"Risk & Compliance Committee","page":2,"section":"2","passage":"Aggregate exposure to non-investment-grade instruments (High Yield + Structured Credit) must not exceed 20% of NAV."},
    "liquidity_ratio":             {"min":25.0,"max":None,"unit":"% NAV","breach_action":"Report to Risk & Compliance Committee within 24h","owner":"Risk & Compliance Committee","page":2,"section":"3.3","passage":"Liquid assets (SGS + MAS Bills + Cash) must constitute a minimum of 25% of NAV under normal conditions."},
}

NON_IG_CLASSES = {"High Yield Bonds", "Structured Credit"}
LIQUID_CLASSES  = {"Singapore Government Securities", "MAS Bills", "Cash & Cash Equivalents"}

def extract_text_chunks(pdf_path):
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            chunks.append({"page": i+1, "chunk_id": _chunk_id(text, f"p{i+1}"), "text": text})
    return chunks

def build_graph(guidelines_pdf=GUIDELINES_PDF, holdings_csv=HOLDINGS_CSV):
    G = nx.DiGraph()
    now = _now()
    chunks = extract_text_chunks(guidelines_pdf)

    for ac_name, lim in ALLOCATION_LIMITS.items():
        chunk = chunks[lim["page"]-1]
        G.add_node(f"AssetClass:{ac_name}", node_type="AssetClass", name=ac_name,
            min_pct=lim["min_pct"], max_pct=lim["max_pct"], notes=lim["notes"],
            source_doc="sample_fund_guidelines.pdf", page=lim["page"], chunk_id=chunk["chunk_id"],
            section=lim["section"], passage=lim["passage"], ingestion_time=now, extraction_confidence=1.0)

    for m_name, m in RISK_METRICS.items():
        chunk = chunks[m["page"]-1]
        G.add_node(f"RiskMetric:{m_name}", node_type="RiskMetric", name=m_name,
            min_val=m["min"], max_val=m["max"], unit=m["unit"],
            breach_action=m["breach_action"], owner=m["owner"],
            source_doc="sample_fund_guidelines.pdf", page=m["page"], chunk_id=chunk["chunk_id"],
            section=m["section"], passage=m["passage"], ingestion_time=now, extraction_confidence=1.0)

    G.add_node("Aggregate:non_ig", node_type="AggregateLimit", name="Aggregate non-IG exposure",
        max_pct=20.0, constituent_classes=list(NON_IG_CLASSES),
        source_doc="sample_fund_guidelines.pdf", page=2, chunk_id=chunks[1]["chunk_id"],
        section="2", passage="Aggregate exposure to non-investment-grade instruments (High Yield + Structured Credit) must not exceed 20% of NAV.",
        ingestion_time=now, extraction_confidence=1.0)

    G.add_node("Aggregate:liquidity", node_type="AggregateLimit", name="Liquid assets ratio",
        min_pct=25.0, constituent_classes=list(LIQUID_CLASSES),
        source_doc="sample_fund_guidelines.pdf", page=2, chunk_id=chunks[1]["chunk_id"],
        section="3.3", passage="Liquid assets (SGS + MAS Bills + Cash) must constitute a minimum of 25% of NAV under normal conditions.",
        ingestion_time=now, extraction_confidence=1.0)

    for cls in NON_IG_CLASSES:
        G.add_edge(f"AssetClass:{cls}", "Aggregate:non_ig", rel="CONTRIBUTES_TO", ingestion_time=now)
    for cls in LIQUID_CLASSES:
        G.add_edge(f"AssetClass:{cls}", "Aggregate:liquidity", rel="CONTRIBUTES_TO", ingestion_time=now)

    with open(holdings_csv, newline="") as f:
        holdings = list(csv.DictReader(f))

    issuers_seen, parents_seen = {}, {}
    for h in holdings:
        iid = h["instrument_id"]
        ac_canonical = ASSET_CLASS_MAP.get(h["asset_class"], h["asset_class"])
        issuer = h["issuer_name"]
        parent = h["parent_issuer"].strip() or None
        mv = float(h["market_value_sgd"])
        dur = float(h["modified_duration"])

        G.add_node(f"Position:{iid}", node_type="Position",
            instrument_id=iid, instrument_name=h["instrument_name"],
            asset_class_raw=h["asset_class"], asset_class_canonical=ac_canonical,
            issuer_name=issuer, issuer_type=h["issuer_type"].strip(),
            parent_issuer=parent, credit_rating=h["credit_rating"].strip(),
            downgraded_from=h["downgraded_from"].strip(),
            market_value_sgd=mv, modified_duration=dur,
            source_doc="sample_holdings.csv", page=None,
            chunk_id=_chunk_id(iid, "pos"), ingestion_time=now, extraction_confidence=1.0)

        ac_node = f"AssetClass:{ac_canonical}"
        if ac_node in G.nodes:
            G.add_edge(f"Position:{iid}", ac_node, rel="BELONGS_TO", ingestion_time=now)

        issuer_node = f"Issuer:{issuer}"
        if issuer_node not in issuers_seen:
            G.add_node(issuer_node, node_type="Issuer", name=issuer,
                issuer_type=h["issuer_type"].strip(), parent_issuer=parent,
                source_doc="sample_holdings.csv", chunk_id=_chunk_id(issuer,"iss"),
                ingestion_time=now, extraction_confidence=1.0)
            issuers_seen[issuer_node] = True
        G.add_edge(f"Position:{iid}", issuer_node, rel="ISSUED_BY", ingestion_time=now)

        if parent:
            parent_node = f"ParentIssuer:{parent}"
            if parent_node not in parents_seen:
                G.add_node(parent_node, node_type="ParentIssuer", name=parent,
                    source_doc="sample_holdings.csv", chunk_id=_chunk_id(parent,"par"),
                    ingestion_time=now, extraction_confidence=1.0)
                parents_seen[parent_node] = True
            G.add_edge(issuer_node, parent_node, rel="GROUPED_UNDER", ingestion_time=now)

    return G
