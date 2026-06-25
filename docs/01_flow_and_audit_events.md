# Phase 1 — AS-IS / TO-BE Flow & Audit Event Catalogue

## AS-IS Process

```
Analyst reads guidelines PDF
        ↓
Analyst pulls numbers from holdings snapshot (manual)
        ↓
Analyst computes each allocation / utilization / breach in a spreadsheet
        ↓
Analyst types results into report template
        ↓
Report distributed to Risk & Compliance Committee
```

**Problems with AS-IS:**
- No audit trail from source passage → final number
- Easy to introduce transcription errors
- Hard to defend in an audit: "which formula, which cell, which version?"
- Cannot reproduce independently

---

## TO-BE Process

```
[HUMAN INPUT]        sample_fund_guidelines.pdf  +  sample_holdings.csv
                              ↓
[SYSTEM — PHASE 2]   Graph Builder (deterministic extraction)
                     Ingests all guidelines rules + positions → NetworkX graph
                     Every node/edge carries: source_doc, page, chunk_id,
                     ingestion_time, extraction_confidence
                              ↓
                     ┌─────────────────────────────────────┐
                     │  HUMAN REVIEW GATE 1                │
                     │  Criterion: any node has            │
                     │  extraction_confidence < 0.95       │
                     │  → Human must approve before        │
                     │    figures are computed             │
                     │  Auto-pass: all confidence ≥ 0.95  │
                     └──────────────┬──────────────────────┘
                                    ↓ (approved)
[SYSTEM — PHASE 3]   Compute Engine (deterministic, graph-traversal only)
                     Traverses graph → computes each figure
                     LLM is NOT in this path
                     Each figure emits: value, graph_path, citation
                              ↓
                     ┌─────────────────────────────────────┐
                     │  HUMAN REVIEW GATE 2                │
                     │  Criterion: any figure returns      │
                     │  status == "ERROR" (untraceable)    │
                     │  OR reconciliation delta > tolerance│
                     │  → Human must investigate           │
                     │  Auto-pass: all figures traceable + │
                     │    within tolerance                 │
                     └──────────────┬──────────────────────┘
                                    ↓ (approved)
[SYSTEM — LLM]       Narrative Generator
                     Receives computed figures only
                     Writes commentary prose
                     Firewall check: no new numbers may appear
                              ↓
[SYSTEM — PHASE 5]   Reconciliation Script
                     Diffs computed vs answer key
                     Verifies traceability (figure → graph path → source)
                     Verifies firewall (LLM introduced no novel numbers)
                              ↓
[OUTPUT]             Populated report_template.xlsx  +  audit_log.db
```

---

## LLM Boundary (Constraint 3)

| What the LLM **may** do | What the LLM **must NOT** do |
|---|---|
| Write narrative commentary on pre-computed figures | Produce, round, or alter any numeric figure |
| Summarise compliance status in prose | Introduce any number absent from compute output |
| Reference figures by their exact computed value | Perform any arithmetic |
| Explain breach context in plain English | Access guidelines or holdings directly |

The boundary is enforced structurally: the LLM is invoked only after `compute_all_figures()` returns, and receives only the final `{figure, value, status, limit}` dict. It has no access to the holdings CSV or guidelines PDF.

---

## Audit Event Catalogue

| Event | Trigger | Data Captured | Retention |
|---|---|---|---|
| `CONFIG_LOADED` | Firm config JSON loaded at run start | firm_id, full config dict | 7 years |
| `GRAPH_BUILT` | Knowledge graph construction complete | node_count, edge_count, node list | 7 years |
| `FIGURES_COMPUTED` | All figures returned by compute engine | figure_count, full figures array (value, status, graph_path, citation per figure) | 7 years |
| `NARRATIVE_GENERATED` | LLM narrative returned | narrative text, firewall check result (passed, violations) | 7 years |
| `NARRATIVE_SKIPPED` | --no-narrative flag set | (none) | 7 years |
| `REPORT_WRITTEN` | XLSX report file written | output file path | 10 years (investor-facing) |
| `RECONCILIATION_COMPLETE` | Reconciliation script finishes | per-figure pass/fail/delta, traceability results, firewall results, overall_pass | 7 years |
| `RUN_COMPLETE` | main.py exits normally | firm_id, report path | 7 years |

All events are stored in `audit/audit_log.db` (SQLite) with:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT (append-only ordering)
- `ts` TEXT UTC timestamp
- `event` TEXT
- `firm_id` TEXT
- `data` TEXT (JSON)

Database triggers `prevent_update` and `prevent_delete` make the table immutable — any UPDATE or DELETE raises `ABORT`. This satisfies the requirement that "no row may be updated or deleted after insertion."
