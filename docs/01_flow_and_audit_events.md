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

**Problems:** No audit trail, easy transcription errors, cannot prove source of any number.

---

## TO-BE Process

```
[INPUT]    sample_fund_guidelines.pdf  +  sample_holdings.csv
                      ↓
[PHASE 2]  graph_builder.py — deterministic extraction → NetworkX graph
           Every node/edge: source_doc, page, chunk_id, ingestion_time, extraction_confidence
                      ↓
           ┌─────────────────────────────────────────┐
           │  HUMAN REVIEW GATE 1                    │
           │  Criterion: extraction_confidence < 0.95│
           │  → Human approves before compute runs   │
           │  Auto-pass: all confidence ≥ 0.95       │
           └──────────────┬──────────────────────────┘
                          ↓
[PHASE 3]  compute.py — graph traversal → figures (NO LLM)
           Each figure: value, graph_path, citation
                          ↓
           ┌─────────────────────────────────────────┐
           │  HUMAN REVIEW GATE 2                    │
           │  Criterion: any figure status == ERROR  │
           │  OR reconciliation delta > tolerance    │
           │  → Human investigates before export     │
           │  Auto-pass: all figures traceable       │
           └──────────────┬──────────────────────────┘
                          ↓
[LLM]      narrative.py — Gemini prose commentary only
           Receives final figures; cannot alter numbers
           Firewall check: no novel numbers in narrative
                          ↓
[PHASE 5]  reconcile.py — diff vs answer key, traceability, firewall
                          ↓
[OUTPUT]   reports/<firm>_report.xlsx  +  audit/audit_log.db
```

---

## LLM Boundary (Constraint 3)

| LLM **may** | LLM **must NOT** |
|---|---|
| Write prose commentary | Produce or alter any number |
| Reference figures by exact value | Introduce numbers not in computed output |
| Summarise compliance status | Perform arithmetic |
| Explain breach context | Access guidelines or holdings directly |

---

## Audit Event Catalogue

| Event | Trigger | Data Captured | Retention |
|---|---|---|---|
| `CONFIG_LOADED` | Firm config JSON loaded | firm_id, full config dict | 7 years |
| `GRAPH_BUILT` | Graph construction complete | node_count, edge_count, node list | 7 years |
| `FIGURES_COMPUTED` | All figures returned by compute engine | figure_count, full figures array (value, status, graph_path, citation) | 7 years |
| `NARRATIVE_GENERATED` | LLM narrative returned | narrative text, firewall result (passed, violations) | 7 years |
| `NARRATIVE_SKIPPED` | GEMINI_API_KEY not set | (none) | 7 years |
| `REPORT_WRITTEN` | XLSX report written | output file path | 10 years |
| `RECONCILIATION_COMPLETE` | Reconciliation finishes | per-figure pass/fail/delta, traceability, firewall, overall_pass | 7 years |
| `RUN_COMPLETE` | main.py exits | firm_id, report path | 7 years |

All events stored in `audit/audit_log.db` (SQLite) with UPDATE/DELETE triggers that raise ABORT.
