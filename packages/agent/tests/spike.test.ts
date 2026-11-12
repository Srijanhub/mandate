import { describe, expect, it } from 'vitest';
import { loadEnvIfPresent, runProviderSpike } from '../src/spike.js';

describe('H1 provider spike', () => {
  it('returns false safely when .env does not exist', () => {
    expect(loadEnvIfPresent('/tmp/mandate-nonexistent-env-file-12345')).toBe(false);
  });

  it('validates a compliant integer-minor-unit proposal', async () => {
    const report = await runProviderSpike({
      config: {
        provider: 'mock',
        mockResponseJson: JSON.stringify({
          merchantId: 'giftshop-verified',
          itemName: 'Blue Ceramic Mug',
          unitPriceMinor: 1850,
          qty: 1,
          totalMinor: 1850,
          currency: 'usd',
          rationale: 'Under the $25 limit from an approved merchant.',
        }),
      },
    });

    expect(report.result.ok).toBe(true);
    if (report.result.ok) {
      expect(report.result.data.currency).toBe('USD');
      expect(report.result.data.totalMinor).toBe(1850);
    }
  });

  it('rejects arithmetic mismatch where unitPriceMinor * qty !== totalMinor', async () => {
    const report = await runProviderSpike({
      config: {
        provider: 'mock',
        mockResponseJson: JSON.stringify({
          merchantId: 'giftshop-verified',
          itemName: 'Blue Ceramic Mug',
          unitPriceMinor: 1000,
          qty: 2,
          totalMinor: 1500,
          currency: 'USD',
          rationale: 'Bad math from LLM.',
        }),
      },
    });

    expect(report.result.ok).toBe(false);
    if (!report.result.ok) {
      expect(report.result.error.code).toBe('SCHEMA_MISMATCH');
    }
  });

  it('fails cleanly with CONFIG_ERROR if gemini has no key', async () => {
    const report = await runProviderSpike({
      config: {
        provider: 'gemini',
        apiKey: undefined,
        maxRetries: 0,
      },
    });

    expect(report.result.ok).toBe(false);
    if (!report.result.ok) {
      expect(report.result.error.code).toBe('CONFIG_ERROR');
    }
  });
});
