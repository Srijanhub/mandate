import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { generateStructured, loadLlmConfigFromEnv, redactSecret } from '../src/llm.js';

const QuoteSchema = z.object({
  merchantId: z.string().min(1),
  totalMinor: z.number().int().positive(),
  currency: z.string().length(3),
});

const noSleep = async () => {};

describe('loadLlmConfigFromEnv', () => {
  it('always locks gemini model to gemini-3.8-flash and reads env overrides', () => {
    const cfg = loadLlmConfigFromEnv({
      GEMINI_API_KEY: 'test-secret-key',
      LLM_MODEL: 'gemini-3.5-flash-lite',
      LLM_TIMEOUT_MS: '8000',
    });
    expect(cfg.provider).toBe('gemini');
    expect(cfg.model).toBe('gemini-3.8-flash');
    expect(cfg.apiKey).toBe('test-secret-key');
    expect(cfg.timeoutMs).toBe(8000);
  });

  it('keeps mock only for offline tests and routes unknown providers to gemini', () => {
    expect(loadLlmConfigFromEnv({ LLM_PROVIDER: 'mock' }).provider).toBe('mock');
    expect(loadLlmConfigFromEnv({ LLM_PROVIDER: 'ollama' }).provider).toBe('gemini');
  });
});

describe('generateStructured', () => {
  it('calls Interactions API with gemini-3.8-flash and keeps API key in header, not URL', async () => {
    let seenUrl = '';
    let seenHeaderKey: string | null = null;
    let seenModel = '';

    const fakeFetch: typeof fetch = async (input, init) => {
      seenUrl = String(input);
      seenHeaderKey = new Headers(init?.headers).get('x-goog-api-key');
      const reqBody = JSON.parse(String(init?.body ?? '{}')) as { model?: string };
      seenModel = reqBody.model ?? '';
      return new Response(
        JSON.stringify({
          id: 'int_123',
          status: 'completed',
          outputs: [{ type: 'text', text: '{"merchantId":"giftshop","totalMinor":2500,"currency":"USD"}' }],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };

    const result = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: { provider: 'gemini', model: 'gemini-2.5-flash', apiKey: 'super-secret-123', maxRetries: 0 },
      fetchFn: fakeFetch,
      sleepFn: noSleep,
    });

    expect(seenUrl).toBe('https://generativelanguage.googleapis.com/v1beta/interactions');
    expect(seenUrl).not.toContain('super-secret-123');
    expect(seenHeaderKey).toBe('super-secret-123');
    expect(seenModel).toBe('gemini-3.8-flash');
    expect(result).toEqual({
      ok: true,
      data: { merchantId: 'giftshop', totalMinor: 2500, currency: 'USD' },
      provider: 'gemini',
      model: 'gemini-3.8-flash',
    });
  });

  it('strips markdown json fences before parsing output_text', async () => {
    const fakeFetch: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          output_text: '```json\n{"merchantId":"books","totalMinor":1999,"currency":"USD"}\n```',
        }),
        { status: 200 },
      );

    const result = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy book',
      schema: QuoteSchema,
      config: { provider: 'gemini', apiKey: 'secret-abc', maxRetries: 0 },
      fetchFn: fakeFetch,
      sleepFn: noSleep,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.totalMinor).toBe(1999);
    }
  });

  it('retries on transient 503 service_unavailable and extracts steps text', async () => {
    let calls = 0;
    const fakeFetch: typeof fetch = async () => {
      calls += 1;
      if (calls === 1) {
        return new Response(
          JSON.stringify({ error: { code: 'service_unavailable', message: 'high demand' } }),
          { status: 503 },
        );
      }
      return new Response(
        JSON.stringify({
          steps: [{ type: 'text', text: '{"merchantId":"local_shop","totalMinor":1200,"currency":"USD"}' }],
        }),
        { status: 200 },
      );
    };

    const result = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: { provider: 'gemini', apiKey: 'secret-503', maxRetries: 1 },
      fetchFn: fakeFetch,
      sleepFn: noSleep,
    });

    expect(calls).toBe(2);
    expect(result.ok).toBe(true);
  });

  it('supports mock provider offline', async () => {
    const result = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: {
        provider: 'mock',
        mockResponseJson: '{"merchantId":"mock_shop","totalMinor":500,"currency":"USD"}',
      },
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.provider).toBe('mock');
    }
  });

  it('rejects non-JSON LLM output with INVALID_JSON', async () => {
    const result = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: { provider: 'mock', mockResponseJson: 'Sure! Here is your gift.' },
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe('INVALID_JSON');
    }
  });

  it('rejects non-integer minor currency or missing fields with SCHEMA_MISMATCH', async () => {
    const result = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: {
        provider: 'mock',
        mockResponseJson: '{"merchantId":"giftshop","totalMinor":25.5,"currency":"USD"}',
      },
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe('SCHEMA_MISMATCH');
    }
  });

  it('retries on 429 RATE_LIMITED and succeeds when next attempt passes', async () => {
    let calls = 0;
    const fakeFetch: typeof fetch = async () => {
      calls += 1;
      if (calls === 1) {
        return new Response('rate limited', { status: 429 });
      }
      return new Response(
        JSON.stringify({
          candidates: [
            {
              content: {
                parts: [{ text: '{"merchantId":"giftshop","totalMinor":3000,"currency":"USD"}' }],
              },
            },
          ],
        }),
        { status: 200 },
      );
    };

    const result = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: { provider: 'gemini', apiKey: 'secret-retry', maxRetries: 1 },
      fetchFn: fakeFetch,
      sleepFn: noSleep,
    });

    expect(calls).toBe(2);
    expect(result.ok).toBe(true);
  });

  it('returns TIMEOUT when request exceeds timeoutMs', async () => {
    const hangingFetch: typeof fetch = async (_input, init) =>
      new Promise((_, reject) => {
        init?.signal?.addEventListener('abort', () => {
          const err = new Error('Aborted');
          err.name = 'AbortError';
          reject(err);
        });
      });

    const result = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: { provider: 'gemini', apiKey: 'secret-timeout', timeoutMs: 20, maxRetries: 0 },
      fetchFn: hangingFetch,
      sleepFn: noSleep,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe('TIMEOUT');
    }
  });

  it('redacts secrets from error details and requires API key for gemini', async () => {
    const missingKey = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: { provider: 'gemini', apiKey: undefined, maxRetries: 0 },
    });
    expect(missingKey.ok).toBe(false);
    if (!missingKey.ok) {
      expect(missingKey.error.code).toBe('CONFIG_ERROR');
    }

    const fakeSecret = 'AIzaSyFakeSecretValue999';
    const leakyFetch: typeof fetch = async () =>
      new Response(`Bad key: ${fakeSecret}`, { status: 400 });

    const badRes = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: { provider: 'gemini', apiKey: fakeSecret, maxRetries: 0 },
      fetchFn: leakyFetch,
      sleepFn: noSleep,
    });

    expect(badRes.ok).toBe(false);
    if (!badRes.ok) {
      expect(JSON.stringify(badRes.error)).not.toContain(fakeSecret);
      expect(redactSecret(`token=${fakeSecret}`, fakeSecret)).toBe('token=[REDACTED]');
    }
  });
});
