# RFC — Meridian Compliance Report Engine

## Problem

Asset managers must prove to an MAS auditor that every compliance report number came from a specific source passage, computed by a specific method, and was not produced by an LLM. Five hard constraints drive the design.

## Constraint 3 — LLM cannot produce any reported number

Enforced structurally, not by policy:

- `compute_all_figures()` runs first. It never calls the LLM API.
- `generate_narrative()` is called only after compute finishes, receives only `List[FigureResult]`, has no access to source documents.
- `firewall_check()` verifies no numeric token in the narrative is absent from the computed output.

An auditor can verify this by reading `main.py` in under 10 minutes.

## Constraint 2 — Traceability through the graph

Every `FigureResult` carries:
```json
{
  "graph_path": "(Position:HY-01 | Position:HY-02)-[:BELONGS_TO]->(AssetClass:High Yield Bonds)-[:CONTRIBUTES_TO]->(Aggregate:non_ig)",
  "citation": {
    "source_doc": "sample_fund_guidelines.pdf",
    "page": 2,
    "chunk_id": "p2_7f6467ea",
    "passage_summary": "Aggregate non-IG ... must not exceed 20% of NAV."
  }
}
```
Figures that cannot be traced return `{"status":"ERROR"}` — never silently emitted.

## Constraint 5 — Firm reconfiguration without code changes

Three flags in a JSON file cover all Firm B differences:
```json
{
  "non_ig_include_fallen_angels": true,
  "gre_concentration_at_parent": true,
  "utilization_format": "truncated_bps"
}
```
Every compute function reads from `firm_config["conventions"]`. Switching firms = changing the `--firm` argument. No engine file is modified.

## Constraint 4 — Reconciliation to answer key

`reconcile.py` compares computed vs expected value and status strings exactly. Tolerance: duration rounded to 2dp, DV01 to nearest integer SGD — both match the answer key exactly.

## Constraint 1 — Reproducibility

All arithmetic is pure Python on fixed inputs. No random seeds, no floating-point accumulation differences between runs. Same inputs → byte-identical figures.

## Production additions

- Secret management (Vault / AWS Secrets Manager) for Gemini API key
- RBAC on audit log DB
- Signed hash of each report XLSX recorded in audit trail
- Human review UI for Gate 1 (low-confidence extraction) and Gate 2 (untraceable figures)
