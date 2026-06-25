"""
main.py — InterOpera Compliance Report Engine entrypoint.

Usage:
    python main.py --firm firm_A          # Firm A report + reconciliation
    python main.py --firm firm_B          # Firm B report + reconciliation
    python main.py --firm firm_A --no-narrative   # Skip LLM narrative

The firm config file (config/<firm_id>.json) drives all computation differences
between firms — no engine code changes needed (constraint 5).
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(__file__)
sys.path.insert(0, BASE_DIR)

from engine.graph_builder import build_graph
from engine.compute import compute_all_figures
from engine.narrative import generate_narrative, firewall_check
from engine.report_writer import write_report
from engine.reconcile import reconcile, print_reconciliation_report
from engine.audit import log_event

ANSWER_KEYS = {
    "firm_A": os.path.join(BASE_DIR, "sample_docs", "firm_A_answer_key.xlsx"),
    # Firm B uses same key structure; for this submission Firm B's differing
    # figures are validated in the reconciliation output (not a separate xlsx)
    "firm_B": os.path.join(BASE_DIR, "sample_docs", "firm_B_answer_key.xlsx"),
}


def load_firm_config(firm_id: str) -> dict:
    config_path = os.path.join(BASE_DIR, "config", f"{firm_id}.json")
    if not os.path.exists(config_path):
        print(f"ERROR: config/{firm_id}.json not found")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="InterOpera Compliance Report Engine")
    parser.add_argument("--firm", default="firm_A", help="Firm ID (firm_A or firm_B)")
    parser.add_argument("--no-narrative", action="store_true", help="Skip LLM narrative generation")
    args = parser.parse_args()

    firm_id = args.firm
    print(f"\n{'='*60}")
    print(f"InterOpera Compliance Report Engine")
    print(f"Firm: {firm_id}")
    print(f"{'='*60}\n")

    # ── 1. Load firm configuration ──────────────────────────────────────────
    firm_config = load_firm_config(firm_id)
    print(f"[1/6] Loaded config: {firm_config['firm_name']}")
    log_event("CONFIG_LOADED", {"firm_id": firm_id, "config": firm_config}, firm_id=firm_id)

    # ── 2. Build knowledge graph ─────────────────────────────────────────────
    print("[2/6] Building knowledge graph from guidelines + holdings...")
    G = build_graph()
    node_count = G.number_of_nodes()
    edge_count = G.number_of_edges()
    print(f"      Graph: {node_count} nodes, {edge_count} edges")
    log_event("GRAPH_BUILT", {
        "node_count": node_count,
        "edge_count": edge_count,
        "nodes": list(G.nodes()),
    }, firm_id=firm_id)

    # ── 3. Compute figures (deterministic, graph-traversal only) ────────────
    print("[3/6] Computing figures by graph traversal (no LLM in this path)...")
    figures = compute_all_figures(G, firm_config)
    print(f"      Computed {len(figures)} figures")
    log_event("FIGURES_COMPUTED", {
        "firm_id": firm_id,
        "figure_count": len(figures),
        "figures": figures,
    }, firm_id=firm_id)

    # ── 4. Generate narrative (LLM-only, no numbers may be introduced) ──────
    narrative = ""
    firewall_result = {}
    if not args.no_narrative:
        print("[4/6] Generating LLM narrative commentary...")
        narrative = generate_narrative(figures, firm_config)
        firewall_result = firewall_check(narrative, figures)
        fw_status = "PASSED" if firewall_result["passed"] else "FAILED"
        print(f"      Firewall check: {fw_status}")
        if not firewall_result["passed"]:
            print(f"      Violations: {firewall_result['violations']}")
        log_event("NARRATIVE_GENERATED", {
            "narrative": narrative,
            "firewall": firewall_result,
        }, firm_id=firm_id)
    else:
        print("[4/6] Narrative skipped (--no-narrative)")
        log_event("NARRATIVE_SKIPPED", {}, firm_id=firm_id)

    # ── 5. Write report XLSX ────────────────────────────────────────────────
    print("[5/6] Writing report XLSX...")
    output_path = write_report(figures, firm_id, narrative)
    print(f"      Report: {output_path}")
    log_event("REPORT_WRITTEN", {"output_path": output_path}, firm_id=firm_id)

    # ── 6. Reconcile against answer key ─────────────────────────────────────
    print("[6/6] Reconciling against answer key...")
    answer_key_path = ANSWER_KEYS.get(firm_id, ANSWER_KEYS["firm_A"])
    recon_result = reconcile(figures, answer_key_path, narrative, firewall_result)
    log_event("RECONCILIATION_COMPLETE", recon_result, firm_id=firm_id)

    print_reconciliation_report(recon_result)

    # ── Print all computed figures with graph paths ──────────────────────────
    print("\n--- Computed Figures (with graph paths) ---\n")
    for f in figures:
        print(f"Figure : {f['figure']}")
        print(f"Value  : {f['value']}")
        print(f"Status : {f['status']}")
        print(f"Limit  : {f['limit']}")
        print(f"Util   : {f['utilization']}")
        print(f"Path   : {f['graph_path'][:120]}...")
        cit = f.get("citation", {})
        print(f"Cite   : {cit.get('source_doc')} p{cit.get('page')} [{cit.get('chunk_id')}]")
        print()

    print(f"Done. Report saved to: {output_path}")
    log_event("RUN_COMPLETE", {"firm_id": firm_id, "report": output_path}, firm_id=firm_id)


if __name__ == "__main__":
    main()
