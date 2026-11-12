import { z } from 'zod';

export const LineItemSchema = z.object({
  sku: z.string().min(1),
  name: z.string().min(1),
  unitPriceMinor: z.number().int().positive(),
  qty: z.number().int().positive(),
});

export type LineItem = z.infer<typeof LineItemSchema>;

export const OrderProposalSchema = z.object({
  proposalId: z.string().min(1),
  mandateId: z.string().min(1),
  agentId: z.string().min(1),
  merchantId: z.string().min(1),
  items: z.array(LineItemSchema).min(1),
  totalMinor: z.number().int().positive(),
  currency: z.string().trim().toUpperCase().length(3),
  paypalOrderId: z.string().min(1),
  rationale: z.string().min(1),
  sourceUrl: z.string().url(),
});

export type OrderProposal = z.infer<typeof OrderProposalSchema>;

export const ReasonCodeSchema = z.enum([
  'SIGNATURE_INVALID',
  'EXPIRED',
  'OVER_CAP',
  'CURRENCY_MISMATCH',
  'MERCHANT_NOT_ALLOWED',
  'TOTAL_MISMATCH',
  'APPROVAL_REQUIRED',
]);

export type ReasonCode = z.infer<typeof ReasonCodeSchema>;

export const CheckResultSchema = z.object({
  decision: z.enum(['allow', 'block', 'needs_approval']),
  reasons: z.array(
    z.object({
      code: ReasonCodeSchema,
      message: z.string().min(1),
    }),
  ),
  checkedAt: z.string().min(1),
  mandateHash: z.string().min(1),
});

export type CheckResult = z.infer<typeof CheckResultSchema>;

export interface CreatePayPalOrderInput {
  merchantId: string;
  totalMinor: number;
  currency: string;
  requestId: string;
}

/**
 * Create-order ONLY boundary (Section 8 security rule).
 * Capture and void credentials live strictly in the enforcement service (P3).
 */
export interface PayPalCreateOrderClient {
  createOrder(input: CreatePayPalOrderInput): Promise<{ paypalOrderId: string }>;
}

export interface MandateApiClient {
  submitProposal(proposal: OrderProposal): Promise<CheckResult>;
}
