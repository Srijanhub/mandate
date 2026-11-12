import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { z } from 'zod';
import { generateStructured, type LlmConfig, type LlmResult } from './llm.js';

export const SpikeProposalSchema = z
  .object({
    merchantId: z.string().min(1),
    itemName: z.string().min(1),
    unitPriceMinor: z.number().int().positive(),
    qty: z.number().int().positive(),
    totalMinor: z.number().int().positive(),
    currency: z.string().trim().toUpperCase().length(3),
    rationale: z.string().min(1),
  })
  .refine((val) => val.unitPriceMinor * val.qty === val.totalMinor, {
    message: 'totalMinor must equal unitPriceMinor * qty',
    path: ['totalMinor'],
  });

export type SpikeProposal = z.infer<typeof SpikeProposalSchema>;

export interface SpikeReport {
  result: LlmResult<SpikeProposal>;
  latencyMs: number;
}

export function loadEnvIfPresent(envPath = path.resolve(process.cwd(), '.env')): boolean {
  if (!fs.existsSync(envPath)) {
    return false;
  }
  process.loadEnvFile(envPath);
  return true;
}

export async function runProviderSpike(options?: {
  config?: Partial<LlmConfig>;
  fetchFn?: typeof fetch;
}): Promise<SpikeReport> {
  const started = Date.now();
  const result = await generateStructured({
    systemPrompt: [
      'You are a shopping assistant returning ONLY a JSON object with NO markdown.',
      'Money MUST be integer minor units (cents), e.g., $18.50 is 1850.',
      'Required keys: merchantId, itemName, unitPriceMinor, qty, totalMinor, currency, rationale.',
    ].join(' '),
    userPrompt:
      'Pick 1 birthday ceramic mug under $25 USD from verified merchant "giftshop-verified".',
    schema: SpikeProposalSchema,
    config: options?.config,
    fetchFn: options?.fetchFn,
  });

  return {
    result,
    latencyMs: Date.now() - started,
  };
}

async function main(): Promise<void> {
  const loadedEnv = loadEnvIfPresent();
  console.log(`[H1 Spike] .env loaded: ${loadedEnv}`);

  const report = await runProviderSpike();
  if (report.result.ok) {
    console.log(
      `[H1 Spike] SUCCESS (${report.result.provider} / ${report.result.model} in ${report.latencyMs}ms):`,
    );
    console.log(JSON.stringify(report.result.data, null, 2));
    return;
  }

  console.error(`[H1 Spike] FAILED in ${report.latencyMs}ms:`, JSON.stringify(report.result.error));
  process.exitCode = 1;
}

const isMainModule =
  process.argv[1] !== undefined && pathToFileURL(process.argv[1]).href === import.meta.url;

if (isMainModule) {
  void main();
}
