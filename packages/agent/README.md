# `@mandate/agent` — Autonomous Shopping Agent, Staged Attacks & Intent Receipts

Owner: **Harshit (`H`)** · Modules completed: **H1, H2, H3, H4 (lightweight), S4**

## Architecture

```text
User Goal + Staged Store URL
        │
        ▼
[src/agent.ts: runShoppingAgent] (maxSteps-bounded loop)
   ├── browse_page ──▶ [src/tools.ts: browsePage] (SSRF guard, timeout, HTML text extraction)
   └── propose_order ─▶ [src/tools.ts: proposeOrder]
                            ├── PayPalCreateOrderClient (create-only; NO capture/void creds)
                            └── MandateApiClient (POST /proposals)
                                     │
                                     ▼
                           [src/receipt.ts: generateIntentReceipt]
                           (Code-verified facts + optional LLM summary + SHA-256 hash)
```

## Setup & Commands

```bash
cd packages/agent
npm install
cp .env.example .env   # Add your free Google AI Studio key to GEMINI_API_KEY
```

- **Typecheck & Unit Tests (31 tests, offline):**
  ```bash
  npm run typecheck && npm test
  ```
- **Live Gemini First-Hour Spike:**
  ```bash
  npm run spike
  ```
- **5-Scenario Staged Attack Suite (`H3`):**
  ```bash
  npm run demo:h3
  ```
- **3-Minute Demo Story (`S4`: Injection Blocked + Clean Purchase + Hashed Intent Receipts):**
  ```bash
  npm run demo:story
  ```
- **Connect to Live Backend (`A3`) / Live Gemini (`--live`):**
  ```bash
  MANDATE_API_URL=http://127.0.0.1:3000 npm run demo:story -- --live
  ```

## Security Properties

- **Create-only boundary:** `PayPalCreateOrderClient` exposes only `createOrder`; capture/void credentials live solely in the enforcement service (`P3`).
- **Untrusted LLM validation:** Every LLM response and order draft is parsed via Zod (`zod@4.6.7`) enforcing integer minor currency units (`unitPriceMinor`, `totalMinor`) and arithmetic equality (`unitPriceMinor * qty === totalMinor`).
- **Secret handling:** Gemini API keys are passed via the `x-goog-api-key` header (never URL query strings), redacted in errors (`redactSecret`), and `.env` is git-ignored.

## Honest Disclosure of Mocked & Staged Components

For the hackathon sprint and deterministic verification, the following components inside `@mandate/agent` are mocked or staged and must remain disclosed in the team README and demo video:

1. **Staged Store & Injection Pages (`src/demoPages.ts`):** The five merchant pages (`/clean`, `/injected`, `/wrong-merchant`, `/currency-switch`, `/social-engineering`) are hosted locally on `127.0.0.1` (`<!-- [STAGED DEMO] -->`). The hidden injection demonstrates what happens when an AI model is compromised and why deterministic policy enforcement is required.
2. **Mocked Verified-Seller Allowlist (`DEFAULT_DEMO_MANDATE`):** `"giftshop-verified"` simulates a verified PayPal merchant allowlist.
3. **Standalone Stubs (`createStubPayPalClient`, `createLocalPolicyMirrorClient`):** Used when running `packages/agent` standalone before connecting `P2` (PayPal Orders v2 sandbox) and `A3` (`POST /proposals`). Set `MANDATE_API_URL` to switch to the live API.
4. **LLM Mock / Scripted Replay (`LLM_PROVIDER=mock` / `staged-scripted` / `[STAGED COMPROMISED AGENT]`):** Used in offline Vitest tests, as a demo fallback if Google AI Studio hits `429` rate limits, and for Beat 1 of `demo:story` so the hidden-injection `$400.00 USD` `BLOCK` triggers deterministically even when a live Gemini model resists the injection on its own. With `--live`, Beat 2 and both Intent Receipts call live Gemini (`gemini-3.5-flash-lite`), while `npm run demo:h3 -- --live` probes live-model behavior across all 5 HTML fixtures.
