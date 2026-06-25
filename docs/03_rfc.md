# RFC — Meridian Compliance Report Engine
**Author:** Candidate  
**Date:** 2024  
**Status:** Submitted

---

## Problem statement

Asset managers must prove, to an MAS audit examiner, that every number in a compliance report came from a specific source passage, was computed by a specific method, and was not produced or altered by a language model. The current manual process cannot provide this proof. We need a system that is reproducible, traceable, LLM-number-free, reconfigurable across firms, and reconcilable to an expected answer key.

These five constraints drive every architectural decision below.

---

## How the system structurally guarantees the LLM cannot produce any reported number (Constraint 3)

The system is divided into two strictly separated phases:

**Phase A — Deterministic compute layer** (`graph_builder.py`, `compute.py`): reads source documents, builds the knowledge graph, traverses the graph, and produces `List[FigureResult]`. The LLM API is never called anywhere in this phase. All numeric operations are Python arithmetic on values read directly from the graph.

**Phase B — Narrative layer** (`narrative.py`): is invoked *after* Phase A has finished. It receives the final `List[FigureResult]` — not the source documents, not the holdings CSV, not the graph — and is asked to write prose commentary referencing those figures. It has no channel to alter or re-derive any number.

**Structural enforcement:** the function `generate_narrative(figures, firm_config)` receives only the serialised figure list. There is no code path that could pass raw holdings data or guideline text to the LLM. The call to `generate_narrative` is made only in `main.py`, after `compute_all_figures()` has already returned.

**Firewall check:** after narrative generation, `firewall_check(narrative, figures)` extracts all numeric tokens from the narrative and verifies that every one is present in the computed output set. Any novel number is a violation logged to the audit trail and surfaced in the reconciliation report.

This is a structural guarantee, not a policy assertion. An auditor can read `main.py` in 10 minutes and verify the sequence.

---

## How a figure is traced through the graph to its source (Constraint 2)

Each `FigureResult` carries:

```json
{
  "figure": "aggregate_non_ig_exposure",
  "value": "15.0%",
  "status": "OK",
  "limit": "max 20%",
  "graph_path": "(AssetClass:High Yield Bonds)<-[:BELONGS_TO]-(Position:HY-01) | ...-[:CONTRIBUTES_TO]->(Aggregate:non_ig)",
  "citation": {
    "source_doc": "sample_fund_guidelines.pdf",
    "page": 2,
    "chunk_id": "p2_7f6467ea",
    "passage_summary": "Aggregate exposure to non-investment-grade instruments ... must not exceed 20% of NAV."
  }
}
```

The `graph_path` is an explicit string of the NetworkX nodes and edges traversed to produce the figure. The `citation` points to the exact page and content-hash chunk of the source document. An auditor runs:

1. Open the figure in the reconciliation report
2. Read the `graph_path` — it lists the positions counted, the asset class node, and the aggregate limit node
3. Read the `citation` — it identifies the exact page and passage in `sample_fund_guidelines.pdf`
4. Open the audit log — `FIGURES_COMPUTED` event records the full figure list with all paths, timestamped

A figure that cannot be resolved to a graph path (e.g., a position whose asset class does not match any node) returns `{"status": "ERROR"}` rather than a value. This makes traceability failures explicit, never silent.

---

## How a firm's method is expressed and switched (Constraint 5)

Firm-specific computation conventions are expressed entirely in a JSON config file:

```json
{
  "firm_id": "firm_A",
  "conventions": {
    "non_ig_include_fallen_angels": false,
    "gre_concentration_at_parent": false,
    "utilization_format": "percent_1dp"
  }
}
```

Every compute function that differs between firms accepts `firm_config` as a parameter and reads from `firm_config["conventions"]`. There are no firm-specific code branches or conditionals outside of these three flag reads.

Switching firms:

```bash
python main.py --firm firm_A   # uses config/firm_A.json
python main.py --firm firm_B   # uses config/firm_B.json
```

No engine file is touched between runs. A new firm's conventions are expressed by dropping a new JSON file in `config/` and running with that firm ID. This satisfies constraint 5 by design.

---

## How output is reconciled to an answer key (Constraint 4)

`reconcile.py` loads the answer key XLSX and, for each metric, compares:
- `expected_value` vs `computed_value` (exact string match; tolerance stated where applicable)
- `expected_status` vs `computed_status`

**Tolerance statement:** All figures in Firm A's answer key are matched exactly. The only figures with non-trivial precision are portfolio modified duration (rounded to 2 decimal places, e.g. `3.88 yrs`) and DV01 (rounded to nearest integer SGD). Both are reproduced exactly by Python's `round()` on the same arithmetic the answer key was derived from.

Reconciliation results are printed to stdout in tabular form and recorded in the audit log under `RECONCILIATION_COMPLETE`.

---

## Graph model

| Node type | Key attributes |
|---|---|
| `AssetClass` | name, min_pct, max_pct, notes, source_doc, page, chunk_id, passage |
| `RiskMetric` | name, min_val, max_val, unit, breach_action, owner, source_doc, page, chunk_id, passage |
| `AggregateLimit` | name, max_pct or min_pct, constituent_classes, source_doc, page, chunk_id, passage |
| `Position` | instrument_id, asset_class_canonical, issuer_name, issuer_type, parent_issuer, credit_rating, downgraded_from, market_value_sgd, modified_duration |
| `Issuer` | name, issuer_type, parent_issuer |
| `ParentIssuer` | name |

| Edge type | From → To | Meaning |
|---|---|---|
| `BELONGS_TO` | Position → AssetClass | Position is classified in this asset class |
| `ISSUED_BY` | Position → Issuer | Position's obligor |
| `GROUPED_UNDER` | Issuer → ParentIssuer | GRE parent rollup |
| `CONTRIBUTES_TO` | AssetClass → AggregateLimit | Asset class is counted in aggregate |
| `GOVERNS` | RiskMetric → AggregateLimit | Risk metric enforces this limit |

Multi-hop query example — "what is the breach action if duration exceeds its limit, and who is notified?":

```python
m = G.nodes["RiskMetric:modified_duration"]
print(m["breach_action"], "→", m["owner"])
# PM notification within 1h → Portfolio Manager
```

---

## What would be added for production

- Secret management (AWS Secrets Manager / Vault) for the LLM API key
- Authentication and RBAC on the audit log DB
- Signed hash of every report XLSX recorded in the audit trail
- Human-review workflow UI for Gate 1 (low-confidence extraction) and Gate 2 (untraceable figures)
- Document version control: re-run detection when guidelines PDF is updated
- Encryption at rest for the audit DB
