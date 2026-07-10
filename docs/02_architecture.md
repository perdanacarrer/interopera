# Phase 1 — Architecture

## Module Map

```
interopera/
├── main.py                    ← Orchestrates all phases
├── Dockerfile + docker-compose.yml
├── config/
│   ├── firm_A.json            ← Firm A conventions
│   └── firm_B.json            ← Firm B conventions (3 flags differ)
├── engine/
│   ├── graph_builder.py       ← Phase 2: PDF + CSV → NetworkX DiGraph
│   ├── compute.py             ← Phase 3: graph traversal → figures (NO LLM)
│   ├── narrative.py           ← LLM boundary (Gemini, prose only)
│   ├── report_writer.py       ← Populates report_template.xlsx
│   ├── reconcile.py           ← Phase 5: diff, traceability, firewall
│   └── audit.py               ← Append-only SQLite audit log
├── sample_docs/               ← Provided materials
├── reports/                   ← Output XLSX (written at runtime)
└── audit/                     ← audit_log.db (written at runtime)
```

## Key Design Decisions

**Firm config as pure data:** All three Firm B differences are flags in `config/firm_B.json`. Zero engine-code changes needed to switch firms (constraint 5).

**Graph as single source of truth:** All figures computed by traversing G. A figure that cannot resolve to a graph path returns `{"status":"ERROR"}` — never silently emitted (constraint 2).

**LLM structurally isolated:** `generate_narrative()` receives only the serialised figure list. No code path passes raw holdings or guidelines to the LLM (constraint 3).

**Audit immutability:** SQLite `BEFORE UPDATE/DELETE` triggers raise ABORT. Demonstrated in code, not merely asserted.
