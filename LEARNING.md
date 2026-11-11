# Learning Log

### T-01 & T-02: Strict Tooling, Fail-Closed Config & Integer Money

- **What we did**: Set up strict TypeScript (`NodeNext`, `exactOptionalPropertyTypes`), Fail-closed environment parsing, domain error types, and integer minor-unit money utilities.
- **Why**: Floating-point math (`0.1 + 0.2`) introduces rounding drift in financial caps, and permissive env defaults cause silent insecurity in production.
- **Core concept**: Store and compare money strictly in integer minor units (cents) parsed from validated decimal strings; fail closed when production secrets or PayPal credentials are absent.
- **Analogy**: Counting physical pennies in sealed jars rather than estimating weights on a bathroom scale.
- **Try it yourself**: Import `parseAmountToMinorUnits` and test `"10.999"` with `"USD"` to verify precision overflow throws `ValidationError`.

### T-03: SQLite Triggers, Invariants & Migration Integrity

- **What we did**: Added versioned SQL migration with SHA-256 verification, database `CHECK` invariants, `BEGIN IMMEDIATE` transaction nesting, and append-only/immutability triggers.
- **Why**: Application checks alone cannot stop accidental SQL updates, concurrent double-spend races, or post-issuance policy tampering.
- **Core concept**: SQLite `IS NOT` handles `NULL` safely in `BEFORE INSERT`/`BEFORE UPDATE` triggers, while `BEGIN IMMEDIATE` serializes writers up front.
- **Analogy**: Welding the vault hinges shut after pouring the concrete—even the vault keeper cannot silently rewrite past ledger pages.
- **Try it yourself**: Run `npm run migrate` twice; the second run verifies migration SHA-256 checksums without re-executing DDL.

### T-04: Canonical JSON, Ed25519 & Domain Separation

- **What we did**: Built deterministic canonical JSON serialization, strict Ed25519 key/signature verification, and full-row SHA-256 ledger hashing.
- **Why**: Key-order drift (`{"a":1,"b":2}` vs `{"b":2,"a":1}`) breaks signature checks, and omitting domain separation allows cross-protocol signature replay.
- **Core concept**: Prefix every signed preimage (`MANDATE_POLICY_V1\n` vs `MANDATE_RECEIPT_V1\n`) and require strict 64-byte canonical Ed25519 signatures.
- **Analogy**: Wax-sealing a contract whose clauses are always sorted alphabetically, with a distinct stamp for checks versus receipts.
- **Try it yourself**: Sign a mandate payload, swap two object keys in the parsed object, and verify canonicalization still produces the exact same digest.

### T-05: Deterministic Policy Engine & Fail-Closed Intent Compiler

- **What we did**: Built the 12-rule deterministic `evaluateMandatePolicy` engine and natural-language `IntentCompiler` (deterministic parser + optional Gemini 3.8 Flash JSON-Schema compiler).
- **Why**: LLMs can be prompt-injected by malicious product descriptions; policy enforcement must remain pure deterministic code over authoritative PayPal data.
- **Core concept**: Separate probabilistic intent drafting (with human confirmation) from deterministic enforcement (fail-closed if any rule or cap is missing).
- **Analogy**: A translator drafts your travel authorization form for your signature, while an automated passport gate checks the ink stamp strictly.
- **Try it yourself**: Pass a prompt without a price cap like `"Buy a gift"` to `compileIntentDeterministic` and observe it reject cleanly.

### T-06: Atomic Repositories & SQL-Injection-Safe Ledger Queries

- **What we did**: Implemented SQLite repositories with atomic `reserveBudget`/`commitReservation`/`releaseReservation`, whitelisted sorting, and streaming hash-chain verification.
- **Why**: AG Grid passes user-controlled sort columns and filters; interpolating column names causes SQL injection, and non-atomic spend checks allow TOCTOU races.
- **Core concept**: Combine `BEGIN IMMEDIATE` + conditional `WHERE spent + reserved + amount <= cap` updates + `SORT_COLUMNS` lookup tables.
- **Analogy**: Putting a single-file turnstile in front of the cash register and checking the menu against a laminated card instead of writing user input on the chalk board.
- **Try it yourself**: Query `GET /api/v1/ledger?sortBy=amountCents&sortDir=desc` and compare against passing an invalid `sortBy`.

### T-07: Resilient PayPal Orders v2 Gateway & Single-Flight OAuth

- **What we did**: Implemented `PayPalHttpGateway` (OAuth2 caching, single-flight token refresh, retries with `PayPal-Request-Id`, multi-unit authorizations, webhook signature verify) and `MockPayPalGateway`.
- **Why**: Concurrent payment bursts must not stampede OAuth endpoints, and retrying `POST` calls safely requires deterministic `PayPal-Request-Id` idempotency keys.
- **Core concept**: Share a single in-flight token promise across concurrent callers, and return all purchase-unit authorizations so multi-unit orders cannot slip past capture or void.
- **Analogy**: Sending one courier to renew the building pass while holding the turnstile line, rather than sending 50 couriers simultaneously.
- **Try it yourself**: Trigger `MockPayPalGateway.configureFaults({ failGetOrderCount: 1 })` in tests to inspect retry recovery or failure handling.

### T-08: Two-Phase Budget Reservation & Crash Reconciliation

- **What we did**: Implemented `KeyService`, `MerchantService`, `MandateService`, `LedgerService`, and `EnforcementService` with two-phase reservation and `reconcileStalePending`.
- **Why**: Holding a SQLite write lock across slow PayPal HTTP calls stalls all traffic, while checking caps without reserving allows concurrent double-spends.
- **Core concept**: Reserve budget atomically in SQLite (`BEGIN IMMEDIATE`), execute PayPal I/O unlocked, then commit or release—plus reconcile interrupted `PENDING` executions.
- **Analogy**: Putting a temporary hold on an airline seat while payment clears, then finalizing the ticket or releasing the seat if the card declines.
- **Try it yourself**: Fire 5 parallel `enforce` requests against a `$40` mandate with `$30` orders and verify only 1 captures.

### T-09: Role-Separated Fastify Boundary & Key Persistence

- **What we did**: Built the Fastify v5 server, constant-time `ADMIN`/`AGENT` RBAC guards, OpenAPI 3.1 docs, uniform error envelope, and persisted dev signing keys.
- **Why**: Agents must never mint or revoke their own spending mandates, and ephemeral dev keys regenerated on restart would invalidate previously issued mandates.
- **Core concept**: Enforce least privilege at the API boundary (`ADMIN` manages policies; `AGENT` only submits enforcement requests) and verify system key public key consistency on startup.
- **Analogy**: Giving the delivery driver a gate pass for checkout counters while keeping the checkbook locked in the manager's safe.
- **Try it yourself**: Call `POST /api/v1/mandates` using `AGENT_API_KEYS` and verify it returns `403 FORBIDDEN`.

### T-10: Exhaustive Testing & Catching Real Bugs

- **What we did**: Built 5 unit and integration test suites (30 tests) covering money parsing, Ed25519 signatures, policy rules, SQLite triggers, concurrency races, and PayPal HTTP retries.
- **Why**: Unit tests for HTTP retry paths uncovered a bug where `401` token refresh left `forceRefresh=true` across subsequent `503` retries.
- **Core concept**: Test adversarial failure modes (tampering, races, partial failures, expired tokens), not only happy paths.
- **Analogy**: Stress-testing a fire door with heat and smoke instead of just checking that the handle turns.
- **Try it yourself**: Run `npm test` and inspect `tests/integration/api_e2e.test.ts` to trace the 5-way concurrent spend race.

### T-11: Compiled Production Build & Live HTTP Smoke Verification

- **What we did**: Documented the full API and setup in `README.md`, compiled TypeScript to `dist/`, and ran a live HTTP smoke flow against `node dist/index.js`.
- **Why**: Unit and `inject()` tests do not exercise compiled ESM path resolution, listening sockets, or graceful `SIGTERM` shutdown.
- **Core concept**: Always verify the compiled production artifact (`dist/index.js`) over real TCP HTTP before declaring backend readiness.
- **Analogy**: Flying the assembled aircraft on a runway check after testing individual wings in the wind tunnel.
- **Try it yourself**: Run `npm run build && npm start` and open `http://localhost:3000/docs` to inspect the live OpenAPI 3.1 contract.

### T-12 & T-13: Core Isolation, Control-Plane Boundary & Production Ship

- **What we did**: Migrated cleanly to Python 3.11+ / FastAPI / SQLAlchemy async (Postgres + SQLite), shipped Docker/Render/CI/Postman assets, and verified 17 tests + ruff + live uvicorn.
- **Why**: Enforcing `mandate_core` isolation via AST tests and keeping `paypal-agent-toolkit` deterministic prevents LLM prompt injection from ever reaching money movement.
- **Core concept**: Separate Core domain rules (`Decimal` Money, Merger, State Machine, Ledger) from Adapters behind Ports (`PaymentProvider`, `Catalog`, `LLM`, `Notifier`).
- **Analogy**: Keeping the bank vault mechanics strictly separate from which courier van or phone line brings the deposit slip.
- **Try it yourself**: Run `.venv/bin/pytest -v` and `POST /demo-lab/run/R3` to watch `PAYEE_MISMATCH` trigger an immediate PayPal `VOID` and ledger entry.
