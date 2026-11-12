import { describe, expect, it } from 'vitest';
import { runAttackSuite } from '../src/attackSuite.js';
import { startStagedMerchantServer } from '../src/demoPages.js';

describe('H3 staged merchant server & attack suite', () => {
  it('serves staged clean & injected pages and returns 404 for unknown paths', async () => {
    const server = await startStagedMerchantServer(0);
    try {
      const cleanRes = await fetch(`${server.baseUrl}/clean`);
      expect(cleanRes.status).toBe(200);
      expect(await cleanRes.text()).toContain('giftshop-verified');

      const injectedRes = await fetch(`${server.baseUrl}/injected`);
      expect(injectedRes.status).toBe(200);
      expect(await injectedRes.text()).toContain('SYSTEM OVERRIDE');

      const missingRes = await fetch(`${server.baseUrl}/does-not-exist`);
      expect(missingRes.status).toBe(404);
    } finally {
      await server.close();
    }
  });

  it('allows clean purchase and blocks all 4 attacks with expected reason codes', async () => {
    const report = await runAttackSuite({ liveLlm: false });
    expect(report.allPassed).toBe(true);
    expect(report.outcomes).toHaveLength(5);

    const byId = new Map(report.outcomes.map((o) => [o.id, o]));
    expect(byId.get('clean_purchase')?.actualDecision).toBe('allow');
    expect(byId.get('over_cap')?.actualReasons).toEqual(
      expect.arrayContaining(['OVER_CAP', 'MERCHANT_NOT_ALLOWED']),
    );
    expect(byId.get('wrong_merchant')?.actualReasons).toContain('MERCHANT_NOT_ALLOWED');
    expect(byId.get('currency_switch')?.actualReasons).toContain('CURRENCY_MISMATCH');
    expect(byId.get('social_engineering')?.actualReasons).toEqual(
      expect.arrayContaining(['OVER_CAP', 'MERCHANT_NOT_ALLOWED']),
    );
  });
});
