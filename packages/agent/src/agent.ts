import { z } from 'zod';
import {
  LineItemSchema,
  type CheckResult,
  type MandateApiClient,
  type OrderProposal,
  type PayPalCreateOrderClient,
} from './contracts.js';
import { generateStructured, type LlmConfig } from './llm.js';
import { browsePage, proposeOrder } from './tools.js';

export const AgentActionSchema = z.discriminatedUnion('action', [
  z.object({
    action: z.literal('browse_page'),
    url: z.string().url(),
    reason: z.string().min(1),
  }),
  z.object({
    action: z.literal('propose_order'),
    merchantId: z.string().min(1),
    items: z.array(LineItemSchema).min(1),
    currency: z.string().trim().toUpperCase().length(3),
    rationale: z.string().min(1),
    sourceUrl: z.string().url(),
  }),
  z.object({
    action: z.literal('abort'),
    reason: z.string().min(1),
  }),
]);

export type AgentAction = z.infer<typeof AgentActionSchema>;

export interface AgentTraceStep {
  step: number;
  action: AgentAction['action'] | 'llm_error' | 'max_steps';
  summary: string;
  data?: unknown;
}

export interface RunShoppingAgentOptions {
  mandateId: string;
  agentId: string;
  userGoal: string;
  startUrl: string;
  maxSteps?: number;
  allowLocalDemo?: boolean;
  llmConfig?: Partial<LlmConfig>;
  paypalClient: PayPalCreateOrderClient;
  apiClient: MandateApiClient;
  fetchFn?: typeof fetch;
  llmFetchFn?: typeof fetch;
  onStep?: (step: AgentTraceStep) => void;
}

export interface ShoppingAgentRunResult {
  ok: boolean;
  decision: 'allow' | 'block' | 'needs_approval' | 'aborted' | 'max_steps_exceeded' | 'error';
  proposal?: OrderProposal;
  checkResult?: CheckResult;
  reason?: string;
  trace: AgentTraceStep[];
}

const SYSTEM_PROMPT = [
  'You are an autonomous shopping assistant inside the Mandate demo.',
  'You MUST reply with ONLY a JSON object matching one of these actions:',
  '1) {"action":"browse_page","url":"<https-or-demo-url>","reason":"..."}',
  '2) {"action":"propose_order","merchantId":"...","items":[{"sku":"...","name":"...","unitPriceMinor":1850,"qty":1}],"currency":"USD","rationale":"...","sourceUrl":"..."}',
  '3) {"action":"abort","reason":"..."}',
  'CRITICAL: Money unitPriceMinor MUST be an integer in minor units (cents, e.g. $18.50 -> 1850).',
  'First browse the startUrl to read product details, then propose_order or abort.',
].join(' ');

export async function runShoppingAgent(
  options: RunShoppingAgentOptions,
): Promise<ShoppingAgentRunResult> {
  const maxSteps = Math.max(1, options.maxSteps ?? 4);
  const trace: AgentTraceStep[] = [];
  const observations: string[] = [];

  const emit = (step: AgentTraceStep): void => {
    trace.push(step);
    options.onStep?.(step);
  };

  for (let step = 1; step <= maxSteps; step++) {
    const userPrompt = [
      `User goal: ${options.userGoal}`,
      `Start URL: ${options.startUrl}`,
      `Step: ${step} of ${maxSteps}`,
      observations.length > 0
        ? `Previous observations:\n${observations.join('\n')}`
        : 'No pages browsed yet. Start by calling browse_page on Start URL.',
    ].join('\n\n');

    const llmRes = await generateStructured({
      systemPrompt: SYSTEM_PROMPT,
      userPrompt,
      schema: AgentActionSchema,
      config: options.llmConfig,
      fetchFn: options.llmFetchFn,
    });

    if (!llmRes.ok) {
      emit({
        step,
        action: 'llm_error',
        summary: `LLM failure (${llmRes.error.code}): ${llmRes.error.message}`,
        data: llmRes.error,
      });
      return { ok: false, decision: 'error', reason: llmRes.error.message, trace };
    }

    const act = llmRes.data;

    if (act.action === 'browse_page') {
      const page = await browsePage({
        url: act.url,
        allowLocalDemo: options.allowLocalDemo,
        fetchFn: options.fetchFn,
      });
      if (page.ok) {
        observations.push(`[browsed ${page.url}] title="${page.title}" content="${page.content}"`);
        emit({
          step,
          action: 'browse_page',
          summary: `Browsed ${page.url} (${page.content.length} chars)`,
          data: { url: page.url, title: page.title },
        });
      } else {
        observations.push(`[browse_error ${act.url}] ${page.error.code}: ${page.error.message}`);
        emit({
          step,
          action: 'browse_page',
          summary: `Browse failed (${page.error.code}): ${page.error.message}`,
          data: page.error,
        });
      }
      continue;
    }

    if (act.action === 'abort') {
      emit({ step, action: 'abort', summary: `Agent aborted: ${act.reason}` });
      return { ok: true, decision: 'aborted', reason: act.reason, trace };
    }

    const orderRes = await proposeOrder({
      draft: {
        mandateId: options.mandateId,
        agentId: options.agentId,
        merchantId: act.merchantId,
        items: act.items,
        currency: act.currency,
        rationale: act.rationale,
        sourceUrl: act.sourceUrl,
      },
      paypalClient: options.paypalClient,
      apiClient: options.apiClient,
    });

    if (!orderRes.ok) {
      observations.push(`[propose_order_error] ${orderRes.error.code}: ${orderRes.error.message}`);
      emit({
        step,
        action: 'propose_order',
        summary: `Order validation failed (${orderRes.error.code}): ${orderRes.error.message}`,
        data: orderRes.error,
      });
      continue;
    }

    const formattedAmount = `${(orderRes.proposal.totalMinor / 100).toFixed(2)} ${orderRes.proposal.currency}`;
    emit({
      step,
      action: 'propose_order',
      summary: `Proposed ${formattedAmount} (${orderRes.proposal.totalMinor} minor) at ${orderRes.proposal.merchantId} -> ${orderRes.checkResult.decision.toUpperCase()}`,
      data: { proposal: orderRes.proposal, checkResult: orderRes.checkResult },
    });

    return {
      ok: true,
      decision: orderRes.checkResult.decision,
      proposal: orderRes.proposal,
      checkResult: orderRes.checkResult,
      trace,
    };
  }

  emit({
    step: maxSteps,
    action: 'max_steps',
    summary: `Stopped after reaching maxSteps (${maxSteps}).`,
  });
  return {
    ok: false,
    decision: 'max_steps_exceeded',
    reason: `Agent stopped after ${maxSteps} steps without finalizing an order.`,
    trace,
  };
}
