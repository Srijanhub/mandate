# TASKS: Mandate Python Backend & Core Board

| ID | Chunk Description | Role | Status | Notes |
|---|---|---|---|---|
| T-01 | Project scaffolding (`pyproject.toml`, `.gitignore`, `.env.example`, `LICENSE`, `.venv` + dependencies) | flex | in_progress | Python 3.11+ FastAPI/SQLAlchemy/Pydantic/google-genai/paypal-agent-toolkit/channel3-sdk |
| T-02 | `mandate_core.domain` & `mandate_core.ports` (Money Decimal, Mandate, Proposal, Case, Finding, Decision, Snapshot, Port ABCs) | backend | done | strict Decimal Money, domain models, zero-dependency Port protocols |
| T-03 | `mandate_core.rules` registry & built-in rules (`max_total`, velocity daily/weekly, `seller_policy`, `deliver_by`, `expires_at`, `max_transactions`, `category_policy`, email pack) | backend | done | 10 shopping rules + 4 email rules + JSON policy packs |
| T-04 | `mandate_core.merger` (`build_snapshot`, `diff`, conflict codes, plain-English `/why` templates) | backend | done | pure snapshot merger + diff + plain-English templates |
| T-05 | `mandate_core.ledger` & `mandate_core.recheck` (canonical SHA-256 hash chain, C1-C8 checkpoints, DriftDetector, ProofGuard) | backend | done | SHA-256 hash chain, Trust Score, C1-C8, DriftDetector, ProofGuard, fail-escalate AI Auditor |
| T-06 | `mandate_core.statemachine`, `Orchestrator`, & `mandate_core.commands` (state transitions, command registry & pre-LLM parser) | backend | done | full Case/Mandate state machines, C1-C8 Orchestrator, unified slash/UI CommandRegistry |
| T-07 | Persistence adapter (`adapters/persistence`: SQLAlchemy async Postgres/SQLite models, advisory lock ledger, `FOR UPDATE` / `SKIP LOCKED` repos & job queue) | database | done | SQLAlchemy async models + Postgres advisory lock/SKIP LOCKED + SQLite test parity |
| T-08 | Catalog & Notifier adapters (`adapters/catalog_mock` ~40 seeded items + price bump, `adapters/catalog_channel3`, `adapters/notifier_console`) | backend | done | 40-item Seller A/B MockCatalog + Channel3 SDK adapter + Console/Webhook Notifier |
| T-09 | PayPal adapter (`adapters/paypal`: `paypal-agent-toolkit` deterministic client + read-only LLM config + webhook verify + sandbox/mock simulator) | backend | done | PayPalPaymentProvider + read-only toolkit helper + MockPayPalProvider |
| T-10 | LLM adapters & AI workflows (`adapters/llm_gemini` with `gemini-3.8-flash`, `adapters/llm_groq`, Mandate Compiler, Shopping Agent 2 tools, `ask_preference`, AI Auditor) | backend | done | Gemini 3.8 Flash Interactions API + Groq fallback + 2-tool agent & workflows |
| T-11 | FastAPI backend (`apps/api`: routers for commands, mandates, cases, catalog, ledger/trust-score, webhooks, demo_lab R1-R9, email_pack, background recheck worker) | api | done | 8 FastAPI routers, unified Control Plane, C7 asyncio recheck worker, OpenAPI 3.1 |
| T-12 | Comprehensive tests (`pytest` + `hypothesis`: core isolation, domain/rules, merger, state machine, commands, catalog contract, compiler golden/adversarial, PayPal/webhooks, R1-R9 E2E) | flex | done | 17/17 tests passing (zero warnings), ruff lint clean |
| T-13 | Deployment & submission pack (`docker-compose.yml`, `Dockerfile`, `render.yaml`, `.github/workflows/ci.yml`, `docs/mandate-postman-collection.json`, `README.md`) & final verification | flex | done | Docker, Render, CI, 38-endpoint Postman collection, live uvicorn smoke passed |
