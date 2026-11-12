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
  it('defaults to gemini and reads env overrides', () => {
    const cfg = loadLlmConfigFromEnv({
      GEMINI_API_KEY: 'test-secret-key',
      LLM_TIMEOUT_MS: '8000',
    });
    expect(cfg.provider).toBe('gemini');
    expect(cfg.model).toBe('gemini-3.5-flash-lite');
    expect(cfg.apiKey).toBe('test-secret-key');
    expect(cfg.timeoutMs).toBe(8000);
  });

  it('switches to ollama via LLM_PROVIDER', () => {
    const cfg = loadLlmConfigFromEnv({ LLM_PROVIDER: 'ollama' });
    expect(cfg.provider).toBe('ollama');
    expect(cfg.model).toBe('llama3.2:3b');
  });
});

describe('generateStructured', () => {
  it('succeeds on valid Gemini JSON and keeps API key in header, not URL', async () => {
    let seenUrl = '';
    let seenHeaderKey: string | null = null;

    const fakeFetch: typeof fetch = async (input, init) => {
      seenUrl = String(input);
      seenHeaderKey = new Headers(init?.headers).get('x-goog-api-key');
      return new Response(
        JSON.stringify({
          candidates: [
            {
              content: {
                parts: [{ text: '{"merchantId":"giftshop","totalMinor":2500,"currency":"USD"}' }],
              },
            },
          ],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    };

    const result = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: { provider: 'gemini', apiKey: 'super-secret-123', maxRetries: 0 },
      fetchFn: fakeFetch,
      sleepFn: noSleep,
    });

    expect(seenUrl).not.toContain('super-secret-123');
    expect(seenHeaderKey).toBe('super-secret-123');
    expect(result).toEqual({
      ok: true,
      data: { merchantId: 'giftshop', totalMinor: 2500, currency: 'USD' },
      provider: 'gemini',
      model: 'gemini-3.5-flash-lite',
    });
  });

  it('strips markdown json fences before parsing', async () => {
    const fakeFetch: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          candidates: [
            {
              content: {
                parts: [
                  {
                    text: '```json\n{"merchantId":"books","totalMinor":1999,"currency":"USD"}\n```',
                  },
                ],
              },
            },
          ],
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

  it('supports ollama provider with local /api/chat payload', async () => {
    let seenUrl = '';
    const fakeFetch: typeof fetch = async (input) => {
      seenUrl = String(input);
      return new Response(
        JSON.stringify({
          message: {
            content: '{"merchantId":"local_shop","totalMinor":1200,"currency":"USD"}',
          },
        }),
        { status: 200 },
      );
    };

    const result = await generateStructured({
      systemPrompt: 'Return JSON',
      userPrompt: 'Buy gift',
      schema: QuoteSchema,
      config: { provider: 'ollama', baseUrl: 'http://localhost:11434', maxRetries: 0 },
      fetchFn: fakeFetch,
      sleepFn: noSleep,
    });

    expect(seenUrl).toBe('http://localhost:11434/api/chat');
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
