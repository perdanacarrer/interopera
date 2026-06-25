# Phase 1 — Architecture

## Module Map

```
interopera/
├── main.py                    ← Entrypoint; orchestrates all phases
├── requirements.txt
├── config/
│   ├── firm_A.json            ← Firm A conventions (no fallen angels, per-issuer GRE, 1dp pct)
│   └── firm_B.json            ← Firm B conventions (fallen angels, parent GRE, truncated bps)
├── engine/
│   ├── graph_builder.py       ← Phase 2: ingests PDF + CSV → NetworkX DiGraph
│   ├── compute.py             ← Phase 3: traverses graph → deterministic figures (NO LLM)
│   ├── narrative.py           ← LLM boundary: commentary only, firewall enforced
│   ├── report_writer.py       ← Populates report_template.xlsx
│   ├── reconcile.py           ← Phase 5: diffs figures vs answer key, traces, firewalls
│   └── audit.py               ← Append-only audit log (SQLite with UPDATE/DELETE triggers)
├── sample_docs/               ← Provided materials (unmodified)
├── reports/                   ← Output XLSX reports
├── audit/                     ← audit_log.db (append-only SQLite)
└── docs/                      ← This documentation
```

## Data Flow

```
sample_fund_guidelines.pdf
        │  pdfplumber text extraction
        ▼
  graph_builder.py ──────── deterministic rule tables ──► NetworkX DiGraph (G)
        ▲                                                         │
sample_holdings.csv                                              │
        │  csv.DictReader                                        │
        └────────────────────────────────────────────────────────┘
                                                                  │
                                                   firm config (JSON)
                                                                  │
                                                                  ▼
                                                         compute.py
                                               (graph traversal, no LLM)
                                                         │
                                                         ▼
                                               List[FigureResult]
                                                    │          │
                                            narrative.py   report_writer.py
                                           (LLM, prose     (populates XLSX
                                            only, firewall   template)
                                            checked)
                                                    │
                                               reconcile.py
                                              (diff vs key)
                                                    │
                                              audit.py (log every event)
```

## Key Design Decisions

### Separation of extraction vs computation
Guidelines are parsed by hand-coded rule tables (not by LLM), encoded directly in `graph_builder.py`. This guarantees extraction_confidence = 1.0 for all nodes in the sample materials. If a future document introduces ambiguous rules, `extraction_confidence` < 0.95 would trigger Gate 1 (human review).

### Graph as the single source of truth
All figures are computed by traversing G, not by re-reading documents. A figure that cannot be resolved to a graph path is returned as an `{"status": "ERROR"}` — it is never silently emitted (constraint 2).

### Firm configuration as pure data
All three Firm B differences (`non_ig_include_fallen_angels`, `gre_concentration_at_parent`, `utilization_format`) are boolean/string flags in `config/firm_B.json`. The compute functions read from `firm_config["conventions"]`. Switching firms = changing the JSON path argument. Zero engine-code changes (constraint 5).

### Audit immutability
SQLite triggers `prevent_update` and `prevent_delete` on `audit_log` raise `ABORT` on any mutation attempt. This is demonstrated in code, not merely asserted.
