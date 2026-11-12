import crypto from 'node:crypto';
import { z } from 'zod';
import {
  CheckResultSchema,
  LineItemSchema,
  OrderProposalSchema,
  type CheckResult,
  type MandateApiClient,
  type OrderProposal,
  type PayPalCreateOrderClient,
} from './contracts.js';

export interface ToolError {
  code: 'INVALID_URL' | 'SSRF_BLOCKED' | 'FETCH_FAILED' | 'INVALID_ORDER' | 'API_ERROR';
  message: string;
  details?: unknown;
}

export type BrowseResult =
  | { ok: true; url: string; title: string; content: string; truncated: boolean }
  | { ok: false; error: ToolError };

export interface BrowsePageOptions {
  url: string;
  timeoutMs?: number;
  maxChars?: number;
  allowLocalDemo?: boolean;
  fetchFn?: typeof fetch;
}

const PRIVATE_IP_PATTERNS = [
  /^10\.\d+\.\d+\.\d+$/,
  /^192\.168\.\d+\.\d+$/,
  /^169\.254\.\d+\.\d+$/,
  /^172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+$/,
  /^0\.0\.0\.0$/,
];

function isLoopbackHost(hostname: string): boolean {
  const h = hostname.toLowerCase();
  return h === 'localhost' || h === '::1' || h === '[::1]' || /^127\.\d+\.\d+\.\d+$/.test(h);
}

function isPrivateNetworkHost(hostname: string): boolean {
  return PRIVATE_IP_PATTERNS.some((pattern) => pattern.test(hostname));
}

export function extractPageTitleAndText(html: string, maxChars: number): {
  title: string;
  content: string;
  truncated: boolean;
} {
  const titleMatch = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(html);
  const title = (titleMatch?.[1] ?? '').replace(/\s+/g, ' ').trim();

  // Strip executable/style blocks; hidden DOM elements remain in extracted text
  // (modeling how naive browsing agents ingest hidden prompt-injection text).
  const withoutScripts = html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, ' ');
  const plain = withoutScripts.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

  const truncated = plain.length > maxChars;
  return {
    title,
    content: truncated ? plain.slice(0, maxChars) : plain,
    truncated,
  };
}

export async function browsePage(options: BrowsePageOptions): Promise<BrowseResult> {
  let parsedUrl: URL;
  try {
    parsedUrl = new URL(options.url);
  } catch {
    return {
      ok: false,
      error: { code: 'INVALID_URL', message: `Malformed URL: ${options.url}` },
    };
  }

  if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') {
    return {
      ok: false,
      error: {
        code: 'INVALID_URL',
        message: `Blocked unsupported URL protocol: ${parsedUrl.protocol}`,
      },
    };
  }

  if (isPrivateNetworkHost(parsedUrl.hostname)) {
    return {
      ok: false,
      error: { code: 'SSRF_BLOCKED', message: `Blocked private IP host: ${parsedUrl.hostname}` },
    };
  }

  if (isLoopbackHost(parsedUrl.hostname) && !options.allowLocalDemo) {
    return {
      ok: false,
      error: { code: 'SSRF_BLOCKED', message: `Blocked loopback host: ${parsedUrl.hostname}` },
    };
  }

  const timeoutMs = options.timeoutMs ?? 8000;
  const maxChars = options.maxChars ?? 12_000;
  const fetchFn = options.fetchFn ?? fetch;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchFn(parsedUrl.toString(), {
      method: 'GET',
      signal: controller.signal,
    });
    if (!response.ok) {
      return {
        ok: false,
        error: {
          code: 'FETCH_FAILED',
          message: `Merchant page returned HTTP ${response.status}`,
        },
      };
    }
    const html = await response.text();
    const { title, content, truncated } = extractPageTitleAndText(html, maxChars);
    return { ok: true, url: parsedUrl.toString(), title, content, truncated };
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'FETCH_FAILED',
        message: err instanceof Error ? err.message : String(err),
      },
    };
  } finally {
    clearTimeout(timer);
  }
}

export const DraftOrderInputSchema = z.object({
  mandateId: z.string().min(1),
  agentId: z.string().min(1),
  merchantId: z.string().min(1),
  items: z.array(LineItemSchema).min(1),
  currency: z.string().trim().toUpperCase().length(3),
  claimedTotalMinor: z.number().int().positive().optional(),
  rationale: z.string().min(1),
  sourceUrl: z.string().url(),
});

export type DraftOrderInput = z.infer<typeof DraftOrderInputSchema>;

export type ProposeOrderResult =
  | { ok: true; proposal: OrderProposal; checkResult: CheckResult }
  | { ok: false; error: ToolError };

export interface ProposeOrderOptions {
  draft: DraftOrderInput;
  paypalClient: PayPalCreateOrderClient;
  apiClient: MandateApiClient;
  proposalId?: string;
  requestId?: string;
}

export async function proposeOrder(options: ProposeOrderOptions): Promise<ProposeOrderResult> {
  const parsedDraft = DraftOrderInputSchema.safeParse(options.draft);
  if (!parsedDraft.success) {
    return {
      ok: false,
      error: {
        code: 'INVALID_ORDER',
        message: 'Order draft failed validation.',
        details: parsedDraft.error.issues.map((i) => ({ path: i.path.join('.'), message: i.message })),
      },
    };
  }

  const draft = parsedDraft.data;
  const totalMinor = draft.items.reduce((sum, item) => sum + item.unitPriceMinor * item.qty, 0);

  if (draft.claimedTotalMinor !== undefined && draft.claimedTotalMinor !== totalMinor) {
    return {
      ok: false,
      error: {
        code: 'INVALID_ORDER',
        message: `Agent arithmetic mismatch: claimed ${draft.claimedTotalMinor} != computed ${totalMinor}.`,
      },
    };
  }

  const proposalId = options.proposalId ?? `prop-${crypto.randomUUID()}`;
  const requestId = options.requestId ?? `req-${crypto.randomUUID()}`;

  try {
    const { paypalOrderId } = await options.paypalClient.createOrder({
      merchantId: draft.merchantId,
      totalMinor,
      currency: draft.currency,
      requestId,
    });

    const proposal = OrderProposalSchema.parse({
      proposalId,
      mandateId: draft.mandateId,
      agentId: draft.agentId,
      merchantId: draft.merchantId,
      items: draft.items,
      totalMinor,
      currency: draft.currency,
      paypalOrderId,
      rationale: draft.rationale,
      sourceUrl: draft.sourceUrl,
    });

    const rawCheck = await options.apiClient.submitProposal(proposal);
    const checkResult = CheckResultSchema.parse(rawCheck);
    return { ok: true, proposal, checkResult };
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'API_ERROR',
        message: err instanceof Error ? err.message : String(err),
      },
    };
  }
}

/**
 * Local create-only stub while P2 is in progress.
 * Notice: exposes ONLY createOrder() — never capture() or void().
 */
export function createStubPayPalClient(): PayPalCreateOrderClient {
  let seq = 0;
  return {
    async createOrder(input) {
      seq += 1;
      return {
        paypalOrderId: `PAYPAL-SANDBOX-STUB-${seq}-${input.currency}-${input.totalMinor}`,
      };
    },
  };
}

export function createHttpMandateApiClient(
  baseUrl: string,
  fetchFn: typeof fetch = fetch,
): MandateApiClient {
  const cleanBase = baseUrl.replace(/\/+$/, '');
  return {
    async submitProposal(proposal) {
      const response = await fetchFn(`${cleanBase}/proposals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(proposal),
      });
      if (!response.ok) {
        const body = (await response.text()).slice(0, 200);
        throw new Error(`POST /proposals failed (${response.status}): ${body}`);
      }
      return CheckResultSchema.parse(await response.json());
    },
  };
}
