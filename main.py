"""
main.py — InterOpera Compliance Report Engine

Usage:
    python main.py --firm firm_A
    python main.py --firm firm_B

Narrative (Google Gemini, free):
    export GEMINI_API_KEY=your_key   # auto-enables narrative
    # Free key: https://aistudio.google.com/app/apikey

Docker:
    docker compose up
    GEMINI_API_KEY=your_key docker compose up
"""
import argparse, json, os, sys
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
    "firm_B": os.path.join(BASE_DIR, "sample_docs", "firm_B_answer_key.xlsx"),
}

def load_firm_config(firm_id):
    path = os.path.join(BASE_DIR, "config", f"{firm_id}.json")
    if not os.path.exists(path):
        print(f"ERROR: config/{firm_id}.json not found"); sys.exit(1)
    with open(path) as f: return json.load(f)

def main():
    parser = argparse.ArgumentParser(description="InterOpera Compliance Report Engine")
    parser.add_argument("--firm", default="firm_A", help="Firm ID: firm_A or firm_B")
    args = parser.parse_args()
    firm_id = args.firm
    has_key = bool(os.environ.get("GEMINI_API_KEY", "").strip())

    print(f"\n{'='*60}")
    print(f"InterOpera Compliance Report Engine")
    print(f"Firm     : {firm_id}")
    print(f"Narrative: {'enabled (GEMINI_API_KEY set)' if has_key else 'skipped (set GEMINI_API_KEY to enable)'}")
    print(f"{'='*60}\n")

    # 1. Config
    firm_config = load_firm_config(firm_id)
    print(f"[1/6] Config: {firm_config['firm_name']}")
    log_event("CONFIG_LOADED", {"firm_id": firm_id, "config": firm_config}, firm_id=firm_id)

    # 2. Graph
    print("[2/6] Building knowledge graph...")
    G = build_graph()
    print(f"      {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    log_event("GRAPH_BUILT", {"node_count": G.number_of_nodes(), "edge_count": G.number_of_edges()}, firm_id=firm_id)

    # 3. Compute (NO LLM)
    print("[3/6] Computing figures by graph traversal (no LLM)...")
    figures = compute_all_figures(G, firm_config)
    print(f"      {len(figures)} figures computed")
    log_event("FIGURES_COMPUTED", {"figures": figures}, firm_id=firm_id)

    # 4. Narrative (LLM — only if key present, skipped gracefully on failure)
    narrative, firewall_result = "", {}
    if has_key:
        print("[4/6] Generating narrative (Gemini)...")
        narrative = generate_narrative(figures, firm_config)
        if narrative and not narrative.startswith("["):
            firewall_result = firewall_check(narrative, figures)
            fw = "✓ PASSED" if firewall_result["passed"] else "✗ FAILED"
            print(f"      Narrative generated. Firewall: {fw}")
            if not firewall_result["passed"]:
                print(f"      Violations: {firewall_result['violations']}")
            log_event("NARRATIVE_GENERATED", {"narrative": narrative, "firewall": firewall_result}, firm_id=firm_id)
        else:
            print("      Narrative skipped (API unavailable or rate-limited)")
            narrative = ""  # ensure nothing bad goes into the xlsx
            log_event("NARRATIVE_SKIPPED", {"reason": "api_error_or_rate_limit"}, firm_id=firm_id)
    else:
        print("[4/6] Narrative skipped (GEMINI_API_KEY not set)")
        log_event("NARRATIVE_SKIPPED", {"reason": "no_api_key"}, firm_id=firm_id)

    # 5. Write report
    print("[5/6] Writing report XLSX...")
    out = write_report(figures, firm_id, narrative)
    print(f"      → {out}")
    log_event("REPORT_WRITTEN", {"output_path": out}, firm_id=firm_id)

    # 6. Reconcile
    print("[6/6] Reconciling against answer key...")
    recon = reconcile(figures, ANSWER_KEYS.get(firm_id, ANSWER_KEYS["firm_A"]), narrative, firewall_result)
    log_event("RECONCILIATION_COMPLETE", recon, firm_id=firm_id)
    print_reconciliation_report(recon)

    log_event("RUN_COMPLETE", {"firm_id": firm_id, "report": out}, firm_id=firm_id)
    print(f"Report saved to: {out}\n")

if __name__ == "__main__":
    main()
