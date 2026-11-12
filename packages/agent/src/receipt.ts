import crypto from 'node:crypto';
import { z } from 'zod';
import type { CheckResult, OrderProposal } from './contracts.js';
import { generateStructured, type LlmConfig } from './llm.js';

export interface IntentReceiptFacts {
  proposalId: string;
  mandateId: string;
  paypalOrderId: string;
  merchantId: string;
  totalMinor: number;
  currency: string;
  decision: CheckResult['decision'];
  reasons: CheckResult['reasons'];
  mandateHash: string;
  checkedAt: string;
  sourceUrl: string;
}

export interface IntentReceipt {
  facts: IntentReceiptFacts;
  narrative: string;
  narrativeSource: 'deterministic-template' | 'llm-narrated';
  receiptHash: string;
}

const NarrativeSchema = z.object({
  summary: z.string().min(10).max(400),
});

export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  }
  const obj = value as Record<string, unknown>;
  const sortedKeys = Object.keys(obj).sort();
  const entries = sortedKeys.map((k) => `${JSON.stringify(k)}:${canonicalJson(obj[k])}`);
  return `{${entries.join(',')}}`;
}

export function formatMinorAmount(totalMinor: number, currency: string): string {
  return `${(totalMinor / 100).toFixed(2)} ${currency}`;
}

export function hasUnscaledMinorLeak(summary: string, facts: IntentReceiptFacts): boolean {
  const formattedMajor = (facts.totalMinor / 100).toFixed(2);
  if (summary.includes(formattedMajor)) {
    return false;
  }
  const currencyPattern = new RegExp(`\\b${facts.totalMinor}\\s*${facts.currency}\\b`, 'i');
  const symbolPattern = new RegExp(`\\$${facts.totalMinor}(?!\\d)`);
  return currencyPattern.test(summary) || symbolPattern.test(summary);
}

export function buildDeterministicNarrative(facts: IntentReceiptFacts): string {
  const formattedAmount = formatMinorAmount(facts.totalMinor, facts.currency);
  if (facts.decision === 'allow') {
    return (
      `Approved ${formattedAmount} at ${facts.merchantId} (PayPal order ${facts.paypalOrderId}) ` +
      `under mandate ${facts.mandateId}; all policy checks passed.`
    );
  }
  const codes = facts.reasons.map((r) => r.code).join(', ') || 'POLICY_VIOLATION';
  return (
    `Blocked ${formattedAmount} at ${facts.merchantId} (PayPal order ${facts.paypalOrderId}) ` +
    `under mandate ${facts.mandateId}; reasons: ${codes}.`
  );
}

export async function generateIntentReceipt(options: {
  proposal: OrderProposal;
  checkResult: CheckResult;
  useLlmNarrative?: boolean;
  llmConfig?: Partial<LlmConfig>;
  llmFetchFn?: typeof fetch;
}): Promise<IntentReceipt> {
  // Facts always come deterministically from verified code — never from LLM text.
  const facts: IntentReceiptFacts = {
    proposalId: options.proposal.proposalId,
    mandateId: options.proposal.mandateId,
    paypalOrderId: options.proposal.paypalOrderId,
    merchantId: options.proposal.merchantId,
    totalMinor: options.proposal.totalMinor,
    currency: options.proposal.currency,
    decision: options.checkResult.decision,
    reasons: options.checkResult.reasons,
    mandateHash: options.checkResult.mandateHash,
    checkedAt: options.checkResult.checkedAt,
    sourceUrl: options.proposal.sourceUrl,
  };

  let narrative = buildDeterministicNarrative(facts);
  let narrativeSource: IntentReceipt['narrativeSource'] = 'deterministic-template';

  if (options.useLlmNarrative) {
    const displayAmount = formatMinorAmount(facts.totalMinor, facts.currency);
    const llmRes = await generateStructured({
      systemPrompt: [
        'Summarize this verified payment enforcement outcome in 1-2 factual sentences as JSON {"summary":"..."}.',
        'CRITICAL: Report the money amount ONLY using displayAmount (never treat totalMinor integers as major currency units).',
        'Do not invent numbers or alter facts.',
      ].join(' '),
      userPrompt: JSON.stringify({ ...facts, displayAmount }),
      schema: NarrativeSchema,
      config: options.llmConfig,
      fetchFn: options.llmFetchFn,
    });
    if (llmRes.ok && !hasUnscaledMinorLeak(llmRes.data.summary, facts)) {
      narrative = llmRes.data.summary;
      narrativeSource = 'llm-narrated';
    }
  }

  const receiptHash = crypto
    .createHash('sha256')
    .update(canonicalJson({ facts, narrative }))
    .digest('hex');

  return {
    facts,
    narrative,
    narrativeSource,
    receiptHash,
  };
}
