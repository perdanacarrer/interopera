"""
compute.py — Deterministic figure computation by graph traversal.

THE LLM IS NOT IN THIS PATH. Every number is computed here by traversing
the knowledge graph. The LLM may only write narrative commentary after
all figures have been produced.

Each compute function returns a FigureResult dict with:
  figure, value, status, limit, utilization, graph_path, citation
"""
from __future__ import annotations

import json
import math
from typing import Any

import networkx as nx

from engine.graph_builder import (
    ASSET_CLASS_MAP,
    NON_IG_CLASSES,
    LIQUID_CLASSES,
    graph_provenance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

IG_RATINGS = {"AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"}


def _is_non_ig_rating(rating: str) -> bool:
    return rating not in IG_RATINGS and rating != ""


def _format_utilization(value: float, limit_val: float | None,
                        is_min: bool, convention: str) -> str:
    """Format utilization according to firm convention."""
    if limit_val is None:
        return "n/a"
    if is_min:
        util = (value / limit_val) * 100.0
    else:
        util = (value / limit_val) * 100.0

    if convention == "truncated_bps":
        bps = int(util * 100)  # truncate, not round
        return f"{bps} bps"
    else:  # percent_1dp
        return f"{round(util, 1)}%"


def _figure_error(name: str, reason: str) -> dict:
    return {
        "figure": name,
        "value": "ERROR",
        "status": "ERROR",
        "limit": None,
        "utilization": None,
        "graph_path": None,
        "citation": {"error": reason},
    }


def _positions_from_graph(G: nx.DiGraph) -> list[dict]:
    return [
        G.nodes[n]
        for n in G.nodes
        if G.nodes[n].get("node_type") == "Position"
    ]


def _total_nav(positions: list[dict]) -> float:
    return sum(p["market_value_sgd"] for p in positions)


# ---------------------------------------------------------------------------
# Allocation figures
# ---------------------------------------------------------------------------

def compute_allocation(G: nx.DiGraph, asset_class_canonical: str,
                       firm_config: dict) -> dict:
    convention = firm_config["conventions"]["utilization_format"]

    ac_node = f"AssetClass:{asset_class_canonical}"
    if ac_node not in G.nodes:
        return _figure_error(f"allocation_{asset_class_canonical}",
                             f"Node {ac_node} not found in graph")

    ac_data = G.nodes[ac_node]
    positions = _positions_from_graph(G)
    nav = _total_nav(positions)

    # Traverse graph: find all Position nodes BELONGS_TO this AssetClass
    position_nodes = [
        n for n in G.predecessors(ac_node)
        if G.nodes[n].get("node_type") == "Position"
    ]

    if not position_nodes:
        total_mv = 0.0
    else:
        total_mv = sum(G.nodes[n]["market_value_sgd"] for n in position_nodes)

    pct = round((total_mv / nav) * 100, 1) if nav else 0.0

    min_pct = ac_data.get("min_pct")
    max_pct = ac_data.get("max_pct")

    # Determine status
    if min_pct is not None and pct < min_pct:
        status = "BREACH"
        limit_str = f"min {min_pct}%"
        util = _format_utilization(pct, min_pct, True, convention)
    elif max_pct is not None and pct > max_pct:
        status = "BREACH"
        limit_str = f"max {max_pct}%"
        util = _format_utilization(pct, max_pct, False, convention)
    elif max_pct is not None and pct == max_pct:
        status = "AT LIMIT"
        limit_str = f"{min_pct}–{max_pct}%" if min_pct is not None and min_pct > 0 else f"max {max_pct}%"
        util = _format_utilization(pct, max_pct, False, convention)
    else:
        status = "OK"
        if min_pct is not None and min_pct > 0 and max_pct is not None:
            limit_str = f"{min_pct}–{max_pct}%"
            util = _format_utilization(pct, max_pct, False, convention)
        elif min_pct is not None and min_pct > 0:
            limit_str = f"min {min_pct}%"
            util = _format_utilization(pct, min_pct, True, convention)
        else:
            limit_str = f"0–{max_pct}%"
            util = _format_utilization(pct, max_pct, False, convention)

    # Special: cash only has a min allocation
    if asset_class_canonical == "Cash & Cash Equivalents":
        if pct < min_pct:
            status = "BREACH"
            limit_str = f"min {min_pct}%"
            util = "n/a"
        else:
            status = "OK"
            limit_str = f"min {min_pct}%"
            util = "n/a"

    graph_path = (
        f"({' | '.join(position_nodes)})"
        f"-[:BELONGS_TO]->(AssetClass:{asset_class_canonical})"
    )

    return {
        "figure": f"allocation_{asset_class_canonical}",
        "value": f"{pct}%",
        "status": status,
        "limit": limit_str,
        "utilization": util,
        "graph_path": graph_path,
        "citation": {
            "source_doc": ac_data["source_doc"],
            "page": ac_data["page"],
            "chunk_id": ac_data["chunk_id"],
            "passage_summary": ac_data["passage"],
        },
    }


# ---------------------------------------------------------------------------
# Aggregate non-IG
# ---------------------------------------------------------------------------

def compute_aggregate_non_ig(G: nx.DiGraph, firm_config: dict) -> dict:
    convention = firm_config["conventions"]["utilization_format"]
    include_fallen_angels = firm_config["conventions"]["non_ig_include_fallen_angels"]

    agg_node = "Aggregate:non_ig"
    if agg_node not in G.nodes:
        return _figure_error("aggregate_non_ig_exposure", "Aggregate:non_ig node not in graph")

    agg_data = G.nodes[agg_node]
    positions = _positions_from_graph(G)
    nav = _total_nav(positions)

    # Find positions contributing to non-IG via graph traversal
    contributing_positions = []
    path_parts = []

    for ac_cls in NON_IG_CLASSES:
        ac_node = f"AssetClass:{ac_cls}"
        pos_nodes = [n for n in G.predecessors(ac_node)
                     if G.nodes[n].get("node_type") == "Position"]
        for pn in pos_nodes:
            contributing_positions.append(G.nodes[pn])
            path_parts.append(f"(AssetClass:{ac_cls})<-[:BELONGS_TO]-(Position:{G.nodes[pn]['instrument_id']})")

    # Fallen angels: IG-classified but sub-IG rating, if firm config says so
    if include_fallen_angels:
        ig_node = "AssetClass:Investment Grade Corporate Bonds"
        ig_pos = [n for n in G.predecessors(ig_node)
                  if G.nodes[n].get("node_type") == "Position"]
        for pn in ig_pos:
            p = G.nodes[pn]
            if _is_non_ig_rating(p["credit_rating"]) and p.get("downgraded_from"):
                # Not already counted
                if p not in contributing_positions:
                    contributing_positions.append(p)
                    path_parts.append(
                        f"(Position:{p['instrument_id']})-[:FALLEN_ANGEL]->(Aggregate:non_ig)"
                    )

    total_mv = sum(p["market_value_sgd"] for p in contributing_positions)
    pct = round((total_mv / nav) * 100, 1) if nav else 0.0
    max_pct = agg_data["max_pct"]

    status = "BREACH" if pct > max_pct else "OK"
    util = _format_utilization(pct, max_pct, False, convention)

    graph_path = (
        " | ".join(path_parts) +
        f"-[:CONTRIBUTES_TO]->(Aggregate:non_ig)"
    )

    return {
        "figure": "aggregate_non_ig_exposure",
        "value": f"{pct}%",
        "status": status,
        "limit": f"max {max_pct}%",
        "utilization": util,
        "graph_path": graph_path,
        "citation": {
            "source_doc": agg_data["source_doc"],
            "page": agg_data["page"],
            "chunk_id": agg_data["chunk_id"],
            "passage_summary": agg_data["passage"],
        },
    }


# ---------------------------------------------------------------------------
# Single issuer concentration
# ---------------------------------------------------------------------------

def compute_single_issuer_concentration(G: nx.DiGraph, firm_config: dict) -> dict:
    convention = firm_config["conventions"]["utilization_format"]
    metric_node = "RiskMetric:single_issuer_concentration"
    metric_data = G.nodes[metric_node]
    max_pct = metric_data["max_val"]

    positions = _positions_from_graph(G)
    nav = _total_nav(positions)

    # Exclude government issuers
    issuer_mv: dict[str, float] = {}
    for p in positions:
        if p["issuer_type"] == "government":
            continue
        if p["issuer_type"] == "GRE":
            continue
        if p["issuer_type"] == "cash":
            continue
        issuer = p["issuer_name"]
        issuer_mv[issuer] = issuer_mv.get(issuer, 0.0) + p["market_value_sgd"]

    if not issuer_mv:
        return _figure_error("single_issuer_concentration", "No corporate issuers found")

    largest_issuer = max(issuer_mv, key=issuer_mv.get)
    largest_mv = issuer_mv[largest_issuer]
    pct = round((largest_mv / nav) * 100, 1)

    if pct > max_pct:
        status = "BREACH"
    elif pct == max_pct:
        status = "AT LIMIT"
    else:
        status = "OK"

    util = _format_utilization(pct, max_pct, False, convention)

    # Find position nodes for this issuer via graph traversal
    issuer_node = f"Issuer:{largest_issuer}"
    pos_nodes = [n for n in G.predecessors(issuer_node)
                 if G.nodes[n].get("node_type") == "Position"]
    graph_path = (
        f"({' | '.join(pos_nodes)})-[:ISSUED_BY]->(Issuer:{largest_issuer})"
        f"<-[:GOVERNS]-(RiskMetric:single_issuer_concentration)"
    )

    return {
        "figure": "largest_single_corporate_issuer",
        "value": f"{pct}%",
        "status": status,
        "limit": f"max {max_pct}%",
        "utilization": util,
        "graph_path": graph_path,
        "citation": {
            "source_doc": metric_data["source_doc"],
            "page": metric_data["page"],
            "chunk_id": metric_data["chunk_id"],
            "passage_summary": metric_data["passage"],
        },
    }


# ---------------------------------------------------------------------------
# GRE concentration
# ---------------------------------------------------------------------------

def compute_gre_concentration(G: nx.DiGraph, firm_config: dict) -> dict:
    convention = firm_config["conventions"]["utilization_format"]
    at_parent = firm_config["conventions"]["gre_concentration_at_parent"]
    metric_node = "RiskMetric:gre_concentration"
    metric_data = G.nodes[metric_node]
    max_pct = metric_data["max_val"]

    positions = _positions_from_graph(G)
    nav = _total_nav(positions)

    gre_positions = [p for p in positions if p["issuer_type"] == "GRE"]

    if at_parent:
        # Group by parent issuer
        group_mv: dict[str, float] = {}
        for p in gre_positions:
            key = p.get("parent_issuer") or p["issuer_name"]
            group_mv[key] = group_mv.get(key, 0.0) + p["market_value_sgd"]
        if not group_mv:
            pct = 0.0
            largest_group = "N/A"
            graph_path = "(No GRE positions)"
        else:
            largest_group = max(group_mv, key=group_mv.get)
            largest_mv = group_mv[largest_group]
            pct = round((largest_mv / nav) * 100, 1)

            # Traverse graph: find parent node, find issuers grouped under it
            parent_node = f"ParentIssuer:{largest_group}"
            issuer_nodes = [n for n in G.predecessors(parent_node)
                            if G.nodes[n].get("node_type") == "Issuer"]
            pos_nodes = []
            for issuern in issuer_nodes:
                pos_nodes += [n for n in G.predecessors(issuern)
                               if G.nodes[n].get("node_type") == "Position"]
            graph_path = (
                f"({' | '.join(pos_nodes)})-[:ISSUED_BY]->(Issuer)"
                f"-[:GROUPED_UNDER]->(ParentIssuer:{largest_group})"
                f"<-[:GOVERNS]-(RiskMetric:gre_concentration)"
            )
    else:
        # Per-issuer
        issuer_mv: dict[str, float] = {}
        for p in gre_positions:
            issuer_mv[p["issuer_name"]] = issuer_mv.get(p["issuer_name"], 0.0) + p["market_value_sgd"]
        if not issuer_mv:
            pct = 0.0
            graph_path = "(No GRE positions)"
        else:
            largest_issuer = max(issuer_mv, key=issuer_mv.get)
            largest_mv = issuer_mv[largest_issuer]
            pct = round((largest_mv / nav) * 100, 1)
            issuer_node = f"Issuer:{largest_issuer}"
            pos_nodes = [n for n in G.predecessors(issuer_node)
                         if G.nodes[n].get("node_type") == "Position"]
            graph_path = (
                f"({' | '.join(pos_nodes)})-[:ISSUED_BY]->(Issuer:{largest_issuer})"
                f"<-[:GOVERNS]-(RiskMetric:gre_concentration)"
            )

    status = "BREACH" if pct > max_pct else ("AT LIMIT" if pct == max_pct else "OK")
    util = _format_utilization(pct, max_pct, False, convention)

    return {
        "figure": "largest_gre_issuer",
        "value": f"{pct}%",
        "status": status,
        "limit": f"max {max_pct}%",
        "utilization": util,
        "graph_path": graph_path,
        "citation": {
            "source_doc": metric_data["source_doc"],
            "page": metric_data["page"],
            "chunk_id": metric_data["chunk_id"],
            "passage_summary": metric_data["passage"],
        },
    }


# ---------------------------------------------------------------------------
# Liquidity ratio
# ---------------------------------------------------------------------------

def compute_liquidity_ratio(G: nx.DiGraph, firm_config: dict) -> dict:
    convention = firm_config["conventions"]["utilization_format"]
    agg_node = "Aggregate:liquidity"
    agg_data = G.nodes[agg_node]
    min_pct = agg_data["min_pct"]

    positions = _positions_from_graph(G)
    nav = _total_nav(positions)

    liquid_pos = []
    path_parts = []
    for cls in LIQUID_CLASSES:
        ac_node = f"AssetClass:{cls}"
        pos_nodes = [n for n in G.predecessors(ac_node)
                     if G.nodes[n].get("node_type") == "Position"]
        for pn in pos_nodes:
            liquid_pos.append(G.nodes[pn])
            path_parts.append(f"(AssetClass:{cls})")

    total_liquid = sum(p["market_value_sgd"] for p in liquid_pos)
    pct = round((total_liquid / nav) * 100, 1) if nav else 0.0

    status = "BREACH" if pct < min_pct else "OK"
    util = _format_utilization(pct, min_pct, True, convention)

    graph_path = (
        " | ".join(path_parts) +
        f"-[:CONTRIBUTES_TO]->(Aggregate:liquidity)"
    )

    return {
        "figure": "liquid_assets_ratio",
        "value": f"{pct}%",
        "status": status,
        "limit": f"min {min_pct}%",
        "utilization": util,
        "graph_path": graph_path,
        "citation": {
            "source_doc": agg_data["source_doc"],
            "page": agg_data["page"],
            "chunk_id": agg_data["chunk_id"],
            "passage_summary": agg_data["passage"],
        },
    }


# ---------------------------------------------------------------------------
# Duration and DV01
# ---------------------------------------------------------------------------

def compute_duration(G: nx.DiGraph, firm_config: dict) -> dict:
    convention = firm_config["conventions"]["utilization_format"]
    metric_data = G.nodes["RiskMetric:modified_duration"]
    min_val = metric_data["min_val"]
    max_val = metric_data["max_val"]

    positions = _positions_from_graph(G)
    nav = _total_nav(positions)

    # Portfolio modified duration = weighted average
    numerator = sum(p["market_value_sgd"] * p["modified_duration"] for p in positions)
    port_dur = round(numerator / nav, 2) if nav else 0.0

    status = "BREACH" if (port_dur < min_val or port_dur > max_val) else "OK"

    graph_path = (
        "(Position:*)-[:BELONGS_TO]->(AssetClass:*)"
        " | weighted_avg(modified_duration)"
        "->(RiskMetric:modified_duration)"
    )

    return {
        "figure": "portfolio_modified_duration",
        "value": f"{port_dur} yrs",
        "status": status,
        "limit": f"{min_val}–{max_val} yrs",
        "utilization": "n/a",
        "graph_path": graph_path,
        "citation": {
            "source_doc": metric_data["source_doc"],
            "page": metric_data["page"],
            "chunk_id": metric_data["chunk_id"],
            "passage_summary": metric_data["passage"],
        },
    }


def compute_dv01(G: nx.DiGraph, firm_config: dict) -> dict:
    convention = firm_config["conventions"]["utilization_format"]
    metric_data = G.nodes["RiskMetric:dv01"]
    max_val = metric_data["max_val"]

    positions = _positions_from_graph(G)
    nav = _total_nav(positions)

    # DV01 = sum(MV * modified_duration / 10000) per position
    dv01 = sum(p["market_value_sgd"] * p["modified_duration"] / 10000.0 for p in positions)
    dv01_rounded = round(dv01)

    status = "BREACH" if dv01_rounded > max_val else "OK"
    util = _format_utilization(dv01_rounded, max_val, False, convention)

    graph_path = (
        "(Position:*) -> sum(MV * duration / 10000)"
        " -> (RiskMetric:dv01)"
    )

    return {
        "figure": "portfolio_dv01",
        "value": f"SGD {dv01_rounded:,} / bp",
        "status": status,
        "limit": f"max {int(max_val):,}",
        "utilization": util,
        "graph_path": graph_path,
        "citation": {
            "source_doc": metric_data["source_doc"],
            "page": metric_data["page"],
            "chunk_id": metric_data["chunk_id"],
            "passage_summary": metric_data["passage"],
        },
    }


# ---------------------------------------------------------------------------
# Master compute entry point
# ---------------------------------------------------------------------------

def compute_all_figures(G: nx.DiGraph, firm_config: dict) -> list[dict]:
    """
    Compute all report figures by graph traversal. Returns list of FigureResult dicts.
    The LLM is never called in this function.
    """
    results = []

    for ac in [
        "Singapore Government Securities",
        "MAS Bills",
        "Investment Grade Corporate Bonds",
        "High Yield Bonds",
        "Foreign Currency Bonds",
        "Structured Credit",
        "Cash & Cash Equivalents",
    ]:
        results.append(compute_allocation(G, ac, firm_config))

    results.append(compute_aggregate_non_ig(G, firm_config))
    results.append(compute_single_issuer_concentration(G, firm_config))
    results.append(compute_gre_concentration(G, firm_config))
    results.append(compute_liquidity_ratio(G, firm_config))
    results.append(compute_duration(G, firm_config))
    results.append(compute_dv01(G, firm_config))

    return results
