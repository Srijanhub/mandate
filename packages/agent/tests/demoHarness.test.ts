import { describe, expect, it } from 'vitest';
import type { CheckResult, OrderProposal } from '../src/contracts.js';
import { runThreeMinuteDemoStory } from '../src/demoHarness.js';
import { canonicalJson, generateIntentReceipt } from '../src/receipt.js';

describe('H4 intent receipt & S4 3-minute demo harness', () => {
  it('computes deterministic SHA-256 receipt hash and preserves code-only facts', async () => {
    const proposal: OrderProposal = {
      proposalId: 'prop-1',
      mandateId: 'mandate-1',
      agentId: 'agent-1',
      merchantId: 'giftshop-verified',
      items: [{ sku: 'MUG-1', name: 'Ceramic Mug', unitPriceMinor: 1999, qty: 1 }],
      totalMinor: 1999,
      currency: 'USD',
      paypalOrderId: 'PAYPAL-1',
      rationale: 'Under $40 cap',
      sourceUrl: 'http://127.0.0.1:4100/clean',
    };
    const checkResult: CheckResult = {
      decision: 'allow',
      reasons: [],
      checkedAt: '2026-11-11T17:00:00.000Z',
      mandateHash: 'abc123',
    };

    expect(canonicalJson({ b: 2, a: 1 })).toBe('{"a":1,"b":2}');

    const r1 = await generateIntentReceipt({ proposal, checkResult });
    const r2 = await generateIntentReceipt({ proposal, checkResult });
    expect(r1.receiptHash).toBe(r2.receiptHash);
    expect(r1.receiptHash).toMatch(/^[a-f0-9]{64}$/);
    expect(r1.narrativeSource).toBe('deterministic-template');
    expect(r1.facts.totalMinor).toBe(1999);
  });

  it('falls back to deterministic narrative if LLM narration fails', async () => {
    const receipt = await generateIntentReceipt({
      proposal: {
        proposalId: 'prop-2',
        mandateId: 'mandate-1',
        agentId: 'agent-1',
        merchantId: 'totally-legit-deals',
        items: [{ sku: 'VIP', name: 'VIP Card', unitPriceMinor: 40000, qty: 1 }],
        totalMinor: 40000,
        currency: 'USD',
        paypalOrderId: 'PAYPAL-2',
        rationale: 'Injected',
        sourceUrl: 'http://127.0.0.1:4100/injected',
      },
      checkResult: {
        decision: 'block',
        reasons: [{ code: 'OVER_CAP', message: 'Exceeds cap' }],
        checkedAt: '2026-11-11T17:01:00.000Z',
        mandateHash: 'abc123',
      },
      useLlmNarrative: true,
      llmConfig: { provider: 'gemini', apiKey: undefined, maxRetries: 0 },
    });

    expect(receipt.narrativeSource).toBe('deterministic-template');
    expect(receipt.narrative).toContain('Blocked 400.00 USD');
    expect(receipt.narrative).toContain('OVER_CAP');
  });

  it('passes displayAmount to LLM receipt narrator and falls back on unscaled minor-unit leaks', async () => {
    const proposal: OrderProposal = {
      proposalId: 'prop-3',
      mandateId: 'mandate-1',
      agentId: 'agent-1',
      merchantId: 'giftshop-verified',
      items: [{ sku: 'MUG-1', name: 'Ceramic Mug', unitPriceMinor: 1999, qty: 1 }],
      totalMinor: 1999,
      currency: 'USD',
      paypalOrderId: 'PAYPAL-3',
      rationale: 'Under $40 cap',
      sourceUrl: 'http://127.0.0.1:4100/clean',
    };
    const checkResult: CheckResult = {
      decision: 'allow',
      reasons: [],
      checkedAt: '2026-11-11T17:02:00.000Z',
      mandateHash: 'abc123',
    };

    let seenPromptBody = '';
    const compliantFetch: typeof fetch = async (_input, init) => {
      seenPromptBody = String(init?.body ?? '');
      return new Response(
        JSON.stringify({
          candidates: [
            {
              content: {
                parts: [
                  {
                    text: JSON.stringify({
                      summary: 'Allowed 19.99 USD order at giftshop-verified under mandate-1.',
                    }),
                  },
                ],
              },
            },
          ],
        }),
        { status: 200 },
      );
    };

    const goodReceipt = await generateIntentReceipt({
      proposal,
      checkResult,
      useLlmNarrative: true,
      llmConfig: { provider: 'gemini', apiKey: 'test-key', maxRetries: 0 },
      llmFetchFn: compliantFetch,
    });
    const parsedRequest = JSON.parse(seenPromptBody) as {
      contents: Array<{ parts: Array<{ text: string }> }>;
    };
    const promptFacts = JSON.parse(parsedRequest.contents[0]!.parts[0]!.text) as {
      displayAmount: string;
    };
    expect(promptFacts.displayAmount).toBe('19.99 USD');
    expect(goodReceipt.narrativeSource).toBe('llm-narrated');
    expect(goodReceipt.narrative).toContain('19.99 USD');

    const leakyFetch: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          candidates: [
            {
              content: {
                parts: [
                  {
                    text: JSON.stringify({
                      summary: 'Allowed transaction for 1999 USD at giftshop-verified.',
                    }),
                  },
                ],
              },
            },
          ],
        }),
        { status: 200 },
      );

    const safeFallback = await generateIntentReceipt({
      proposal,
      checkResult,
      useLlmNarrative: true,
      llmConfig: { provider: 'gemini', apiKey: 'test-key', maxRetries: 0 },
      llmFetchFn: leakyFetch,
    });
    expect(safeFallback.narrativeSource).toBe('deterministic-template');
    expect(safeFallback.narrative).toContain('Approved 19.99 USD');
  });

  it('runs the full 2-beat 3-minute demo story end-to-end', async () => {
    const report = await runThreeMinuteDemoStory({ liveLlm: false });
    expect(report.ok).toBe(true);
    expect(report.beats[0].beat).toBe('injection_blocked');
    expect(report.beats[0].agentMode).toBe('staged-compromised');
    expect(report.beats[0].run.decision).toBe('block');
    expect(report.beats[0].receipt?.receiptHash).toMatch(/^[a-f0-9]{64}$/);

    expect(report.beats[1].beat).toBe('clean_allowed');
    expect(report.beats[1].agentMode).toBe('staged-scripted');
    expect(report.beats[1].run.decision).toBe('allow');
    expect(report.beats[1].receipt?.receiptHash).toMatch(/^[a-f0-9]{64}$/);
  });
});
