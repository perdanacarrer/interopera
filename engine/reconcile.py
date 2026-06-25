"""
reconcile.py — Phase 5: Reconciliation, traceability check, and firewall check.

Produces a readable table comparing computed figures to the answer key,
verifies every figure has a graph path + citation, and checks the narrative
introduces no new numbers (constraint 3).
"""
import os
import json

import openpyxl

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ANSWER_KEY_A = os.path.join(BASE_DIR, "sample_docs", "firm_A_answer_key.xlsx")

# Map answer key metric → our figure key
ANSWER_KEY_METRIC_MAP = {
    "Singapore Government Securities":    "allocation_Singapore Government Securities",
    "MAS Bills":                           "allocation_MAS Bills",
    "Investment Grade Corporate Bonds":    "allocation_Investment Grade Corporate Bonds",
    "High Yield Bonds":                    "allocation_High Yield Bonds",
    "Foreign Currency Bonds (hedged)":     "allocation_Foreign Currency Bonds",
    "Structured Credit (ABS/MBS)":         "allocation_Structured Credit",
    "Cash & Cash Equivalents":             "allocation_Cash & Cash Equivalents",
    "Aggregate non-IG exposure":           "aggregate_non_ig_exposure",
    "Largest single corporate issuer":     "largest_single_corporate_issuer",
    "Largest GRE issuer":                  "largest_gre_issuer",
    "Liquid assets ratio":                 "liquid_assets_ratio",
    "Portfolio modified duration":         "portfolio_modified_duration",
    "Portfolio DV01":                      "portfolio_dv01",
}


def load_answer_key(path: str) -> dict:
    """Load answer key xlsx into dict keyed by metric name."""
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    result = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[1]:
            result[str(row[1]).strip()] = {
                "value": row[2],
                "limit": row[3],
                "utilization": row[4],
                "status": row[5],
            }
    return result


def reconcile(figures: list[dict], answer_key_path: str = ANSWER_KEY_A,
              narrative: str = "", firewall_result: dict = None) -> dict:
    """
    Run full reconciliation.
    Returns dict with per_figure results, traceability, firewall, overall_pass.
    """
    answer_key = load_answer_key(answer_key_path)
    fig_by_key = {f["figure"]: f for f in figures}

    per_figure = []
    all_pass = True

    for metric, fig_key in ANSWER_KEY_METRIC_MAP.items():
        expected = answer_key.get(metric, {})
        computed = fig_by_key.get(fig_key, {})

        exp_val = str(expected.get("value", "")).strip() if expected.get("value") else ""
        exp_status = str(expected.get("status", "")).strip() if expected.get("status") else ""
        comp_val = str(computed.get("value", "")).strip() if computed.get("value") else ""
        comp_status = str(computed.get("status", "")).strip() if computed.get("status") else ""

        val_match = (exp_val == comp_val)
        status_match = (exp_status == comp_status)
        row_pass = val_match and status_match

        if not row_pass:
            all_pass = False

        per_figure.append({
            "metric": metric,
            "expected_value": exp_val,
            "computed_value": comp_val,
            "value_match": val_match,
            "expected_status": exp_status,
            "computed_status": comp_status,
            "status_match": status_match,
            "pass": row_pass,
        })

    # Traceability check
    traceability = []
    for f in figures:
        has_graph_path = bool(f.get("graph_path") and f["graph_path"] != "(No GRE positions)")
        has_citation = bool(f.get("citation") and f["citation"].get("source_doc"))
        traceable = has_graph_path and has_citation
        if not traceable:
            all_pass = False
        traceability.append({
            "figure": f["figure"],
            "has_graph_path": has_graph_path,
            "has_citation": has_citation,
            "traceable": traceable,
        })

    return {
        "per_figure": per_figure,
        "traceability": traceability,
        "firewall": firewall_result or {},
        "overall_pass": all_pass,
    }


def print_reconciliation_report(result: dict):
    """Print a human-readable reconciliation report to stdout."""
    print("\n" + "=" * 80)
    print("RECONCILIATION REPORT")
    print("=" * 80)

    print("\n--- Per-Figure Comparison ---")
    print(f"{'Metric':<40} {'Expected':>12} {'Computed':>12} {'V':>3} {'Exp Status':>12} {'Comp Status':>12} {'S':>3}")
    print("-" * 100)
    for r in result["per_figure"]:
        v = "✓" if r["value_match"] else "✗"
        s = "✓" if r["status_match"] else "✗"
        print(f"{r['metric']:<40} {r['expected_value']:>12} {r['computed_value']:>12} {v:>3} "
              f"{r['expected_status']:>12} {r['computed_status']:>12} {s:>3}")

    print("\n--- Traceability Check ---")
    for t in result["traceability"]:
        icon = "✓" if t["traceable"] else "✗"
        print(f"  {icon} {t['figure']}")

    fw = result.get("firewall", {})
    if fw:
        print("\n--- Firewall Check (LLM numbers vs computed) ---")
        icon = "✓ PASSED" if fw.get("passed") else "✗ FAILED"
        print(f"  {icon}")
        if fw.get("violations"):
            print(f"  Violations (numbers in narrative not in computed output): {fw['violations']}")

    print("\n" + ("=" * 40))
    overall = "✓ ALL CHECKS PASSED" if result["overall_pass"] else "✗ SOME CHECKS FAILED"
    print(f"OVERALL: {overall}")
    print("=" * 40 + "\n")
