"""
compute.py — Deterministic figure computation by graph traversal. NO LLM IN THIS PATH.
"""
from __future__ import annotations
import networkx as nx
from engine.graph_builder import NON_IG_CLASSES, LIQUID_CLASSES

IG_RATINGS = {"AAA","AA+","AA","AA-","A+","A","A-","BBB+","BBB","BBB-"}

def _positions(G): return [G.nodes[n] for n in G.nodes if G.nodes[n].get("node_type")=="Position"]
def _nav(positions): return sum(p["market_value_sgd"] for p in positions)
def _err(name, reason): return {"figure":name,"value":"ERROR","status":"ERROR","limit":None,"utilization":None,"graph_path":None,"citation":{"error":reason}}

def _util(value, limit_val, convention):
    if limit_val is None: return "n/a"
    pct = (value / limit_val) * 100.0
    if convention == "truncated_bps":
        return f"{int(pct * 100)} bps"
    return f"{round(pct, 1)}%"

def compute_allocation(G, ac_name, firm_config):
    conv = firm_config["conventions"]["utilization_format"]
    ac_node = f"AssetClass:{ac_name}"
    if ac_node not in G.nodes: return _err(f"allocation_{ac_name}", f"{ac_node} not in graph")
    ac = G.nodes[ac_node]
    positions = _positions(G)
    nav = _nav(positions)
    pos_nodes = [n for n in G.predecessors(ac_node) if G.nodes[n].get("node_type")=="Position"]
    total_mv = sum(G.nodes[n]["market_value_sgd"] for n in pos_nodes)
    pct = round((total_mv / nav) * 100, 1) if nav else 0.0
    min_p, max_p = ac.get("min_pct"), ac.get("max_pct")

    if ac_name == "Cash & Cash Equivalents":
        status = "BREACH" if pct < min_p else "OK"
        limit_str = f"min {min_p}%"
        util = "n/a"
    elif min_p and pct < min_p:
        status, limit_str = "BREACH", f"min {min_p}%"
        util = _util(pct, min_p, conv)
    elif max_p and pct > max_p:
        status, limit_str = "BREACH", f"max {max_p}%"
        util = _util(pct, max_p, conv)
    else:
        status = "OK"
        if min_p and min_p > 0 and max_p: limit_str = f"{min_p}–{max_p}%"
        elif min_p and min_p > 0:          limit_str = f"min {min_p}%"
        else:                              limit_str = f"0–{max_p}%"
        util = _util(pct, max_p, conv)

    return {"figure": f"allocation_{ac_name}", "value": f"{pct}%", "status": status,
        "limit": limit_str, "utilization": util,
        "graph_path": f"({' | '.join(pos_nodes)})-[:BELONGS_TO]->(AssetClass:{ac_name})",
        "citation": {"source_doc": ac["source_doc"], "page": ac["page"],
                     "chunk_id": ac["chunk_id"], "passage_summary": ac["passage"]}}

def compute_aggregate_non_ig(G, firm_config):
    conv = firm_config["conventions"]["utilization_format"]
    fallen = firm_config["conventions"]["non_ig_include_fallen_angels"]
    agg = G.nodes["Aggregate:non_ig"]
    positions = _positions(G); nav = _nav(positions)
    contrib, parts = [], []
    for cls in NON_IG_CLASSES:
        for n in G.predecessors(f"AssetClass:{cls}"):
            if G.nodes[n].get("node_type")=="Position":
                contrib.append(G.nodes[n]); parts.append(f"(Position:{G.nodes[n]['instrument_id']})->(AssetClass:{cls})")
    if fallen:
        ig = "AssetClass:Investment Grade Corporate Bonds"
        for n in G.predecessors(ig):
            p = G.nodes[n]
            if p.get("node_type")=="Position" and p["credit_rating"] not in IG_RATINGS and p.get("downgraded_from"):
                if p not in contrib:
                    contrib.append(p); parts.append(f"(Position:{p['instrument_id']})-[:FALLEN_ANGEL]->(Aggregate:non_ig)")
    total_mv = sum(p["market_value_sgd"] for p in contrib)
    pct = round((total_mv / nav)*100, 1) if nav else 0.0
    max_p = agg["max_pct"]
    return {"figure":"aggregate_non_ig_exposure","value":f"{pct}%",
        "status":"BREACH" if pct>max_p else "OK","limit":f"max {max_p}%",
        "utilization":_util(pct,max_p,conv),
        "graph_path":" | ".join(parts)+"-[:CONTRIBUTES_TO]->(Aggregate:non_ig)",
        "citation":{"source_doc":agg["source_doc"],"page":agg["page"],"chunk_id":agg["chunk_id"],"passage_summary":agg["passage"]}}

def compute_single_issuer_concentration(G, firm_config):
    conv = firm_config["conventions"]["utilization_format"]
    m = G.nodes["RiskMetric:single_issuer_concentration"]; max_p = m["max_val"]
    positions = _positions(G); nav = _nav(positions)
    issuer_mv = {}
    for p in positions:
        if p["issuer_type"] in ("government","GRE","cash"): continue
        issuer_mv[p["issuer_name"]] = issuer_mv.get(p["issuer_name"],0.0) + p["market_value_sgd"]
    if not issuer_mv: return _err("single_issuer_concentration","No corporate issuers found")
    largest = max(issuer_mv, key=issuer_mv.get)
    pct = round((issuer_mv[largest]/nav)*100,1)
    pos_nodes = [n for n in G.predecessors(f"Issuer:{largest}") if G.nodes[n].get("node_type")=="Position"]
    return {"figure":"largest_single_corporate_issuer","value":f"{pct}%",
        "status":"BREACH" if pct>max_p else ("AT LIMIT" if pct==max_p else "OK"),"limit":f"max {max_p}%",
        "utilization":_util(pct,max_p,conv),
        "graph_path":f"({' | '.join(pos_nodes)})-[:ISSUED_BY]->(Issuer:{largest})<-[:GOVERNS]-(RiskMetric:single_issuer_concentration)",
        "citation":{"source_doc":m["source_doc"],"page":m["page"],"chunk_id":m["chunk_id"],"passage_summary":m["passage"]}}

def compute_gre_concentration(G, firm_config):
    conv = firm_config["conventions"]["utilization_format"]
    at_parent = firm_config["conventions"]["gre_concentration_at_parent"]
    m = G.nodes["RiskMetric:gre_concentration"]; max_p = m["max_val"]
    positions = _positions(G); nav = _nav(positions)
    gre_pos = [p for p in positions if p["issuer_type"]=="GRE"]

    if at_parent:
        group_mv = {}
        for p in gre_pos:
            key = p.get("parent_issuer") or p["issuer_name"]
            group_mv[key] = group_mv.get(key,0.0) + p["market_value_sgd"]
        if not group_mv: pct, path = 0.0, "(No GRE positions)"
        else:
            largest = max(group_mv, key=group_mv.get)
            pct = round((group_mv[largest]/nav)*100,1)
            parent_node = f"ParentIssuer:{largest}"
            issuer_nodes = [n for n in G.predecessors(parent_node) if G.nodes[n].get("node_type")=="Issuer"]
            pos_nodes = [n for issuern in issuer_nodes for n in G.predecessors(issuern) if G.nodes[n].get("node_type")=="Position"]
            path = f"({' | '.join(pos_nodes)})-[:ISSUED_BY]->(Issuer)-[:GROUPED_UNDER]->(ParentIssuer:{largest})"
    else:
        issuer_mv = {}
        for p in gre_pos:
            issuer_mv[p["issuer_name"]] = issuer_mv.get(p["issuer_name"],0.0) + p["market_value_sgd"]
        if not issuer_mv: pct, path = 0.0, "(No GRE positions)"
        else:
            largest = max(issuer_mv, key=issuer_mv.get)
            pct = round((issuer_mv[largest]/nav)*100,1)
            pos_nodes = [n for n in G.predecessors(f"Issuer:{largest}") if G.nodes[n].get("node_type")=="Position"]
            path = f"({' | '.join(pos_nodes)})-[:ISSUED_BY]->(Issuer:{largest})"

    return {"figure":"largest_gre_issuer","value":f"{pct}%",
        "status":"BREACH" if pct>max_p else ("AT LIMIT" if pct==max_p else "OK"),"limit":f"max {max_p}%",
        "utilization":_util(pct,max_p,conv), "graph_path":path,
        "citation":{"source_doc":m["source_doc"],"page":m["page"],"chunk_id":m["chunk_id"],"passage_summary":m["passage"]}}

def compute_liquidity_ratio(G, firm_config):
    conv = firm_config["conventions"]["utilization_format"]
    agg = G.nodes["Aggregate:liquidity"]; min_p = agg["min_pct"]
    positions = _positions(G); nav = _nav(positions)
    liquid_pos, parts = [], []
    for cls in LIQUID_CLASSES:
        for n in G.predecessors(f"AssetClass:{cls}"):
            if G.nodes[n].get("node_type")=="Position":
                liquid_pos.append(G.nodes[n]); parts.append(f"(AssetClass:{cls})")
    total = sum(p["market_value_sgd"] for p in liquid_pos)
    pct = round((total/nav)*100,1) if nav else 0.0
    return {"figure":"liquid_assets_ratio","value":f"{pct}%",
        "status":"BREACH" if pct<min_p else "OK","limit":f"min {min_p}%",
        "utilization":_util(pct,min_p,conv),
        "graph_path":" | ".join(parts)+"-[:CONTRIBUTES_TO]->(Aggregate:liquidity)",
        "citation":{"source_doc":agg["source_doc"],"page":agg["page"],"chunk_id":agg["chunk_id"],"passage_summary":agg["passage"]}}

def compute_duration(G, firm_config):
    m = G.nodes["RiskMetric:modified_duration"]
    positions = _positions(G); nav = _nav(positions)
    dur = round(sum(p["market_value_sgd"]*p["modified_duration"] for p in positions)/nav, 2) if nav else 0.0
    return {"figure":"portfolio_modified_duration","value":f"{dur} yrs",
        "status":"BREACH" if (dur<m["min_val"] or dur>m["max_val"]) else "OK",
        "limit":f"{m['min_val']}–{m['max_val']} yrs","utilization":"n/a",
        "graph_path":"(Position:*)-weighted_avg(modified_duration)->(RiskMetric:modified_duration)",
        "citation":{"source_doc":m["source_doc"],"page":m["page"],"chunk_id":m["chunk_id"],"passage_summary":m["passage"]}}

def compute_dv01(G, firm_config):
    conv = firm_config["conventions"]["utilization_format"]
    m = G.nodes["RiskMetric:dv01"]; max_p = m["max_val"]
    positions = _positions(G)
    dv01 = round(sum(p["market_value_sgd"]*p["modified_duration"]/10000.0 for p in positions))
    return {"figure":"portfolio_dv01","value":f"SGD {dv01:,} / bp",
        "status":"BREACH" if dv01>max_p else "OK","limit":f"max {int(max_p):,}",
        "utilization":_util(dv01,max_p,conv),
        "graph_path":"(Position:*)->sum(MV*duration/10000)->(RiskMetric:dv01)",
        "citation":{"source_doc":m["source_doc"],"page":m["page"],"chunk_id":m["chunk_id"],"passage_summary":m["passage"]}}

def compute_all_figures(G, firm_config):
    """Entry point. LLM is never called here."""
    results = []
    for ac in ["Singapore Government Securities","MAS Bills","Investment Grade Corporate Bonds",
               "High Yield Bonds","Foreign Currency Bonds","Structured Credit","Cash & Cash Equivalents"]:
        results.append(compute_allocation(G, ac, firm_config))
    results.append(compute_aggregate_non_ig(G, firm_config))
    results.append(compute_single_issuer_concentration(G, firm_config))
    results.append(compute_gre_concentration(G, firm_config))
    results.append(compute_liquidity_ratio(G, firm_config))
    results.append(compute_duration(G, firm_config))
    results.append(compute_dv01(G, firm_config))
    return results
