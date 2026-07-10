"""reconcile.py — Phase 5: per-figure diff vs answer key, traceability, and firewall check."""
import os
import openpyxl

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ANSWER_KEY_A = os.path.join(BASE_DIR, "sample_docs", "firm_A_answer_key.xlsx")

METRIC_MAP = {
    "Singapore Government Securities":   "allocation_Singapore Government Securities",
    "MAS Bills":                          "allocation_MAS Bills",
    "Investment Grade Corporate Bonds":   "allocation_Investment Grade Corporate Bonds",
    "High Yield Bonds":                   "allocation_High Yield Bonds",
    "Foreign Currency Bonds (hedged)":    "allocation_Foreign Currency Bonds",
    "Structured Credit (ABS/MBS)":        "allocation_Structured Credit",
    "Cash & Cash Equivalents":            "allocation_Cash & Cash Equivalents",
    "Aggregate non-IG exposure":          "aggregate_non_ig_exposure",
    "Largest single corporate issuer":    "largest_single_corporate_issuer",
    "Largest GRE issuer":                 "largest_gre_issuer",
    "Liquid assets ratio":                "liquid_assets_ratio",
    "Portfolio modified duration":        "portfolio_modified_duration",
    "Portfolio DV01":                     "portfolio_dv01",
}

def load_answer_key(path):
    wb = openpyxl.load_workbook(path); ws = wb.active
    return {str(row[1]).strip(): {"value":row[2],"limit":row[3],"utilization":row[4],"status":row[5]}
            for row in ws.iter_rows(min_row=2, values_only=True) if row[1]}

def reconcile(figures, answer_key_path=ANSWER_KEY_A, narrative="", firewall_result=None):
    key = load_answer_key(answer_key_path)
    fig_by_key = {f["figure"]: f for f in figures}
    per_figure, all_pass = [], True
    for metric, fig_key in METRIC_MAP.items():
        exp = key.get(metric, {}); comp = fig_by_key.get(fig_key, {})
        ev = str(exp.get("value","") or "").strip(); cv = str(comp.get("value","") or "").strip()
        es = str(exp.get("status","") or "").strip(); cs = str(comp.get("status","") or "").strip()
        vm, sm = ev==cv, es==cs
        if not (vm and sm): all_pass = False
        per_figure.append({"metric":metric,"expected_value":ev,"computed_value":cv,"value_match":vm,
                            "expected_status":es,"computed_status":cs,"status_match":sm,"pass":vm and sm})
    traceability = []
    for f in figures:
        ok = bool(f.get("graph_path")) and bool(f.get("citation",{}).get("source_doc"))
        if not ok: all_pass = False
        traceability.append({"figure":f["figure"],"traceable":ok})
    return {"per_figure":per_figure,"traceability":traceability,
            "firewall":firewall_result or {},"overall_pass":all_pass}

def print_reconciliation_report(result):
    print("\n" + "="*80)
    print("RECONCILIATION REPORT")
    print("="*80)
    print(f"\n{'Metric':<40} {'Expected':>12} {'Computed':>12} {'V':>2} {'Exp Status':>12} {'Comp Status':>12} {'S':>2}")
    print("-"*96)
    for r in result["per_figure"]:
        v = "✓" if r["value_match"] else "✗"
        s = "✓" if r["status_match"] else "✗"
        print(f"{r['metric']:<40} {r['expected_value']:>12} {r['computed_value']:>12} {v:>2} "
              f"{r['expected_status']:>12} {r['computed_status']:>12} {s:>2}")
    print("\n--- Traceability ---")
    for t in result["traceability"]:
        print(f"  {'✓' if t['traceable'] else '✗'} {t['figure']}")
    fw = result.get("firewall", {})
    if fw:
        print("\n--- Firewall (LLM numbers vs computed) ---")
        print(f"  {'✓ PASSED' if fw.get('passed') else '✗ FAILED'}")
        if fw.get("violations"): print(f"  Violations: {fw['violations']}")
    print(f"\n{'='*40}")
    print(f"OVERALL: {'✓ ALL CHECKS PASSED' if result['overall_pass'] else '✗ SOME CHECKS FAILED'}")
    print("="*40 + "\n")
