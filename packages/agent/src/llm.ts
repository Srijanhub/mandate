import type { z } from 'zod';

export type LlmProviderName = 'gemini' | 'ollama' | 'mock';

export type LlmErrorCode =
  | 'CONFIG_ERROR'
  | 'TIMEOUT'
  | 'RATE_LIMITED'
  | 'PROVIDER_ERROR'
  | 'INVALID_JSON'
  | 'SCHEMA_MISMATCH';

export interface LlmError {
  code: LlmErrorCode;
  message: string;
  details?: unknown;
}

export type LlmResult<T> =
  | { ok: true; data: T; provider: LlmProviderName; model: string }
  | { ok: false; error: LlmError };

export interface LlmConfig {
  provider: LlmProviderName;
  model: string;
  apiKey?: string;
  baseUrl?: string;
  timeoutMs: number;
  maxRetries: number;
  mockResponseJson?: string;
}

export interface GenerateStructuredOptions<T> {
  systemPrompt: string;
  userPrompt: string;
  schema: z.ZodType<T>;
  config?: Partial<LlmConfig>;
  fetchFn?: typeof fetch;
  sleepFn?: (ms: number) => Promise<void>;
}

const DEFAULT_MODELS: Record<LlmProviderName, string> = {
  gemini: 'gemini-3.5-flash-lite',
  ollama: 'llama3.2:3b',
  mock: 'mock-deterministic',
};

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

export function loadLlmConfigFromEnv(
  env: Record<string, string | undefined> = process.env,
): LlmConfig {
  const rawProvider = (env.LLM_PROVIDER ?? 'gemini').trim().toLowerCase();
  const provider: LlmProviderName =
    rawProvider === 'ollama' || rawProvider === 'mock' ? rawProvider : 'gemini';

  return {
    provider,
    model: env.LLM_MODEL?.trim() || DEFAULT_MODELS[provider],
    apiKey: env.LLM_API_KEY?.trim() || env.GEMINI_API_KEY?.trim(),
    baseUrl: env.OLLAMA_BASE_URL?.trim() || 'http://localhost:11434',
    timeoutMs: parsePositiveInt(env.LLM_TIMEOUT_MS, 30_000),
    maxRetries: parsePositiveInt(env.LLM_MAX_RETRIES, 2),
    mockResponseJson: env.LLM_MOCK_JSON,
  };
}

export function redactSecret(text: string, secret?: string): string {
  if (!secret || secret.length < 4) return text;
  return text.split(secret).join('[REDACTED]');
}

export function stripMarkdownFences(raw: string): string {
  const trimmed = raw.trim();
  const fenceMatch = /^```(?:json)?\s*\n?([\s\S]*?)\n?```$/i.exec(trimmed);
  return fenceMatch?.[1] !== undefined ? fenceMatch[1].trim() : trimmed;
}

async function defaultSleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

type RawCallResult =
  | { ok: true; text: string }
  | { ok: false; retryable: boolean; error: LlmError };

async function callGeminiRaw(
  systemPrompt: string,
  userPrompt: string,
  config: LlmConfig,
  fetchFn: typeof fetch,
  signal: AbortSignal,
): Promise<RawCallResult> {
  if (!config.apiKey) {
    return {
      ok: false,
      retryable: false,
      error: {
        code: 'CONFIG_ERROR',
        message: 'Missing GEMINI_API_KEY (or LLM_API_KEY) for gemini provider.',
      },
    };
  }

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(config.model)}:generateContent`;
  const response = await fetchFn(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-goog-api-key': config.apiKey,
    },
    body: JSON.stringify({
      systemInstruction: { parts: [{ text: systemPrompt }] },
      contents: [{ role: 'user', parts: [{ text: userPrompt }] }],
      generationConfig: {
        responseMimeType: 'application/json',
        temperature: 0,
      },
    }),
    signal,
  });

  if (response.status === 429) {
    return {
      ok: false,
      retryable: true,
      error: { code: 'RATE_LIMITED', message: 'Gemini rate limit reached (HTTP 429).' },
    };
  }
  if (!response.ok) {
    const bodyText = redactSecret(await response.text(), config.apiKey).slice(0, 300);
    return {
      ok: false,
      retryable: response.status >= 500,
      error: {
        code: 'PROVIDER_ERROR',
        message: `Gemini API returned HTTP ${response.status}.`,
        details: bodyText,
      },
    };
  }

  const json = (await response.json()) as {
    candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
  };
  const text = json.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!text) {
    return {
      ok: false,
      retryable: false,
      error: { code: 'PROVIDER_ERROR', message: 'Gemini returned no text candidate.' },
    };
  }
  return { ok: true, text };
}

async function callOllamaRaw(
  systemPrompt: string,
  userPrompt: string,
  config: LlmConfig,
  fetchFn: typeof fetch,
  signal: AbortSignal,
): Promise<RawCallResult> {
  const baseUrl = (config.baseUrl ?? 'http://localhost:11434').replace(/\/+$/, '');
  const response = await fetchFn(`${baseUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: config.model,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt },
      ],
      stream: false,
      format: 'json',
      options: { temperature: 0 },
    }),
    signal,
  });

  if (!response.ok) {
    const bodyText = (await response.text()).slice(0, 300);
    return {
      ok: false,
      retryable: response.status >= 500,
      error: {
        code: 'PROVIDER_ERROR',
        message: `Ollama returned HTTP ${response.status}.`,
        details: bodyText,
      },
    };
  }

  const json = (await response.json()) as { message?: { content?: string } };
  const text = json.message?.content;
  if (!text) {
    return {
      ok: false,
      retryable: false,
      error: { code: 'PROVIDER_ERROR', message: 'Ollama returned empty message content.' },
    };
  }
  return { ok: true, text };
}

async function dispatchProvider(
  systemPrompt: string,
  userPrompt: string,
  config: LlmConfig,
  fetchFn: typeof fetch,
  signal: AbortSignal,
): Promise<RawCallResult> {
  if (config.provider === 'mock') {
    if (!config.mockResponseJson) {
      return {
        ok: false,
        retryable: false,
        error: {
          code: 'CONFIG_ERROR',
          message: 'Mock provider requires mockResponseJson or LLM_MOCK_JSON.',
        },
      };
    }
    return { ok: true, text: config.mockResponseJson };
  }
  if (config.provider === 'ollama') {
    return callOllamaRaw(systemPrompt, userPrompt, config, fetchFn, signal);
  }
  return callGeminiRaw(systemPrompt, userPrompt, config, fetchFn, signal);
}

export async function generateStructured<T>(
  options: GenerateStructuredOptions<T>,
): Promise<LlmResult<T>> {
  const baseConfig = loadLlmConfigFromEnv();
  const config: LlmConfig = { ...baseConfig, ...options.config };
  const fetchFn = options.fetchFn ?? fetch;
  const sleepFn = options.sleepFn ?? defaultSleep;

  let rawResult: RawCallResult = {
    ok: false,
    retryable: false,
    error: { code: 'PROVIDER_ERROR', message: 'No attempt executed.' },
  };

  for (let attempt = 0; attempt <= config.maxRetries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), config.timeoutMs);
    try {
      rawResult = await dispatchProvider(
        options.systemPrompt,
        options.userPrompt,
        config,
        fetchFn,
        controller.signal,
      );
    } catch (err) {
      const isTimeout = err instanceof Error && err.name === 'AbortError';
      const safeMsg = redactSecret(err instanceof Error ? err.message : String(err), config.apiKey);
      rawResult = {
        ok: false,
        retryable: !isTimeout,
        error: {
          code: isTimeout ? 'TIMEOUT' : 'PROVIDER_ERROR',
          message: isTimeout
            ? `LLM request timed out after ${config.timeoutMs}ms.`
            : `Network failure calling ${config.provider}: ${safeMsg}`,
        },
      };
    } finally {
      clearTimeout(timer);
    }

    if (rawResult.ok || !rawResult.retryable || attempt === config.maxRetries) {
      break;
    }
    await sleepFn(200 * (attempt + 1));
  }

  if (!rawResult.ok) {
    return { ok: false, error: rawResult.error };
  }

  const cleaned = stripMarkdownFences(rawResult.text);
  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(cleaned);
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'INVALID_JSON',
        message: 'LLM output was not valid JSON.',
        details: err instanceof Error ? err.message : String(err),
      },
    };
  }

  const validated = options.schema.safeParse(parsedJson);
  if (!validated.success) {
    return {
      ok: false,
      error: {
        code: 'SCHEMA_MISMATCH',
        message: 'LLM JSON failed schema validation.',
        details: validated.error.issues.map((issue) => ({
          path: issue.path.join('.'),
          message: issue.message,
        })),
      },
    };
  }

  return {
    ok: true,
    data: validated.data,
    provider: config.provider,
    model: config.model,
  };
}
