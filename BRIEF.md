# BRIEF: Mandate — Core Engine & Mandate Shop Backend (Python / FastAPI / Postgres)

**Mode**: `full` (control layer for AI agent spending, Postgres/async state machine, PayPal sandbox, hash-chained ledger, LLM integrations)  
**Target**: Complete production- and hackathon-ready backend (`packages/core/mandate_core`, `adapters/*`, `apps/api`, `tests/*`, deployment configs, Postman collection) — excluding frontend (`apps/web`).

---

## 1. Core Architectural Laws (Non-Negotiable)

1. **LLM never enforces anything**: LLM outputs are schema-validated data only; deterministic Python (`mandate_core.rules`, `merger`, `statemachine`) decides every allow/block.
2. **LLM can only tighten, never loosen**: AI Auditor returns `{verdict: ok|flag|block, reasons[]}` and can never approve; timeout defaults to `flag`.
3. **Control plane vs. data plane**: Deterministic `/` slash-command parser runs *before* any LLM call. Untrusted product descriptions, catalog data, or agent output can never trigger commands.
4. **Fail closed**: Timeouts, missing data, or upstream errors equal not approved.
5. **Atomic state + ledger**: Every state transition, checkpoint (C1–C8), and illegal transition attempt writes a hash-chained `ledger_entries` row in the same DB transaction.
6. **Exact money**: `Decimal` + uppercase ISO-4217 currency everywhere—never float.
7. **Idempotency everywhere**: `PayPal-Request-Id` on all mutating PayPal calls; webhook deduplication by `event_id`.
8. **One code path**: REST endpoints (UI buttons) and `/` slash commands invoke the exact same `Orchestrator` handlers.
9. **Core isolation**: `packages/core/mandate_core` has zero imports from `adapters/` or `apps/` (enforced by automated test).

---

## 2. Stack & Integrations

- **Language & API**: Python 3.11+, FastAPI, Pydantic v2, OpenAPI 3.1.
- **Database**: PostgreSQL (SQLAlchemy 2.0 async + `asyncpg`, `SELECT ... FOR UPDATE SKIP LOCKED` for `recheck_jobs`, `pg_advisory_xact_lock` for linear ledger chain, `JSONB` snapshots/payloads) with seamless `sqlite+aiosqlite` support for local zero-dependency tests.
- **LLM (`LLM` port)**:
  - Primary: Google Gemini (`google-genai`, model `gemini-3.8-flash` — upgraded from deprecated `gemini-2.0-flash`/`2.5-flash` per current SDK guidance, `temperature=0`, structured JSON `response_format` + Interactions tool calling).
  - Fallback: Groq (`groq`, `llama-3.3-70b-versatile`) + deterministic offline fallback.
- **Payment (`PaymentProvider` port)**: `paypal-agent-toolkit` deterministic API client (`get_paypal_api()` / REST `create_order` -> `authorize` -> `capture`/`void` -> `get_order`, `PayPal-Request-Id`, webhook signature verification) + read-only advisory toolkit wrapper + stateful Sandbox/Mock adapter for tests and red-team Demo Lab.
- **Catalog (`Catalog` port)**: `MockCatalog` (~40 seeded items split across Seller A and Seller B + admin price-bump/stock-toggle) and `Channel3Catalog` (`channel3-sdk`) behind the identical `Catalog` contract.
- **Notifier (`Notifier` port)**: Console / Webhook / Zapier-compatible adapter.
- **Testing**: `pytest`, `pytest-asyncio`, `hypothesis`, `httpx`, `ruff`.

---

## 3. Domain State Machines, Merger & Recheck Checkpoints

- **Mandate Lifecycle**: `DRAFT -> ACTIVE -> (REVOKED | EXPIRED)`. `/amend` increments version and keeps prior versions in DB/ledger.
- **Case Lifecycle**: `PROPOSED -> CART_LOCKED -> CHECKED -> AWAITING_APPROVAL -> APPROVED -> AUTHORIZED -> CAPTURED -> VERIFIED`, plus `HELD`, `CANCELLED`, `BLOCKED`, `NEEDS_RECONFIRM`, `EXPIRED`, `FLAGGED`.
- **Merger (`build_snapshot`, `diff`)**: Facts precedence `PayPal > fresh catalog fetch > agent claim`; rules `Mandate` always wins. Conflict codes: `PRICE_DRIFT`, `PAYEE_MISMATCH`, `CURRENCY_MISMATCH`, `QTY_MISMATCH`, `SELLER_CHANGED`, `OUT_OF_STOCK`, `AMOUNT_MISMATCH`, plus plain-English templates for `/why`.
- **Recheck System**:
  - Policy Engine (`@register_rule`: `max_total`, `max_spend_per_day`, `max_spend_per_week`, `seller_policy`, `deliver_by`, `expires_at`, `max_transactions`, `category_policy`, plus domain-agnostic email policy pack `max_recipients`, `allowlist_domain`). Runs all rules without short-circuiting.
  - Drift Detector + AI Auditor.
  - Checkpoints `C1..C8`, background asyncio sweep polling `recheck_jobs` every 30s (`SKIP LOCKED`), and `ProofGuard` verification after capture.

---

## 4. Acceptance Criteria & Definition of Done

1. `tests/unit/test_core_isolation.py` proves `mandate_core` has zero imports from `adapters` or `apps`.
2. Hypothesis property tests prove any total > mandate cap always blocks and `Money` rejects floats/overflow.
3. Merger catches `PRICE_DRIFT` and `PAYEE_MISMATCH`; `/why` renders plain-English rule breakdown.
4. Control-plane parser runs pre-LLM and rejects slash commands embedded inside product descriptions/agent outputs.
5. `ledger_entries` hash chain verifies cleanly via `GET /ledger/verify` and pinpoints tampered rows.
6. All 9 Demo Lab red-team scenarios (`R1..R9`), email policy pack demo, `ask_preference` subset validation, webhook dedup, and `recheck_jobs` sweep pass end-to-end.
7. Docker Compose, Render manifest, GitHub Actions CI, Postman collection, and honest sandbox-vs-real README ship verified.
