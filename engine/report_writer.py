"""
report_writer.py — Populates the report_template.xlsx with computed figures.

Maps computed FigureResult dicts to the template rows and writes the output.
"""
import os
import shutil

import openpyxl

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
TEMPLATE  = os.path.join(BASE_DIR, "sample_docs", "report_template.xlsx")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

# Map template "Metric" column → figure key
METRIC_TO_FIGURE = {
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


def write_report(figures: list[dict], firm_id: str, narrative: str = "") -> str:
    """
    Write figures into the report template and save to reports/<firm_id>_report.xlsx.
    Returns the output path.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    output_path = os.path.join(REPORTS_DIR, f"{firm_id}_report.xlsx")
    shutil.copy(TEMPLATE, output_path)

    wb = openpyxl.load_workbook(output_path)
    ws = wb.active

    # Index figures by key
    fig_by_key = {f["figure"]: f for f in figures}

    for row in ws.iter_rows(min_row=2):
        metric_cell = row[1]  # Column B = Metric
        if metric_cell.value is None:
            continue
        metric = str(metric_cell.value).strip()
        fig_key = METRIC_TO_FIGURE.get(metric)
        if not fig_key:
            continue
        fig = fig_by_key.get(fig_key)
        if not fig:
            continue

        row[2].value = fig.get("value")       # C = Value
        row[3].value = fig.get("limit")       # D = Limit
        row[4].value = fig.get("utilization") # E = Utilization
        row[5].value = fig.get("status")      # F = Status
        # G = Source (graph path)
        gp = fig.get("graph_path", "")
        cit = fig.get("citation", {})
        source_str = f"{gp} | {cit.get('source_doc','')} p{cit.get('page','')} [{cit.get('chunk_id','')}]"
        row[6].value = source_str

    # Add narrative in a new sheet if provided
    if narrative:
        if "Narrative" in wb.sheetnames:
            del wb["Narrative"]
        ns = wb.create_sheet("Narrative")
        ns["A1"] = "Compliance Commentary (LLM-generated — numbers must match computed figures)"
        ns["A2"] = narrative

    wb.save(output_path)
    return output_path
