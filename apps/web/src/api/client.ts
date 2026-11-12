import type {
  AgentTrustScore,
  AmendMandateRequest,
  AuthConfigResponse,
  AuthSessionResponse,
  AuthUserResponse,
  BryntumTimelineResponse,
  CaseListResponse,
  CaseResponse,
  CaseState,
  CatalogSearchResponse,
  CommandResponse,
  DemoLabRunResult,
  ElasticSearchResponse,
  ElasticSyncResponse,
  EmailPolicyCheckRequest,
  EmailPolicyCheckResponse,
  HealthResponse,
  IntegrationsStatusResponse,
  IntentReceipt,
  KernelVerifyUrlResponse,
  LedgerListResponse,
  LedgerVerificationResult,
  MandateDraftResponse,
  MandateListResponse,
  MandateResponse,
  PhoneOtpRequestResponse,
  ProposeCaseRequest,
  ReadyResponse,
  RenderWorkflowRunResponse,
  RevokeAllResponse,
  ShoppingAgentResponse,
  ShoppingOptionsResponse,
  SnapshotDiffResponse,
  SnapshotListResponse,
  WhyResponse,
  ZapierTestResponse,
} from './types';

export class MandateApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(message: string, status: number, code = 'API_ERROR', details?: unknown) {
    super(message);
    this.name = 'MandateApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, '') || '/api';

type TokenAccessor = () => string | null;
type UnauthHandler = () => void;

let getTokenFn: TokenAccessor = () => null;
let onUnauthorizedFn: UnauthHandler = () => {};

export function configureApiAuth(getToken: TokenAccessor, onUnauthorized: UnauthHandler): void {
  getTokenFn = getToken;
  onUnauthorizedFn = onUnauthorized;
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  { skipAuth = false, suppressUnauthorizedHook = false } = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const token = skipAuth ? null : getTokenFn();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });
  } catch (err) {
    throw new MandateApiError(
      err instanceof Error ? `Network error reaching Mandate API: ${err.message}` : 'Network error',
      0,
      'NETWORK_ERROR',
    );
  }

  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { detail: text };
    }
  }

  if (!res.ok) {
    if (res.status === 401 && !suppressUnauthorizedHook) {
      onUnauthorizedFn();
    }
    const obj = (parsed && typeof parsed === 'object' ? parsed : {}) as Record<string, unknown>;
    const nestedErr = obj.error as Record<string, unknown> | undefined;
    const message =
      (nestedErr?.message as string) ||
      (typeof obj.detail === 'string' ? obj.detail : '') ||
      (Array.isArray(obj.detail)
        ? obj.detail.map((d) => (d as { msg?: string }).msg || JSON.stringify(d)).join('; ')
        : '') ||
      `Request failed (${res.status})`;
    const code = (nestedErr?.code as string) || `HTTP_${res.status}`;
    throw new MandateApiError(message, res.status, code, nestedErr?.details ?? obj.detail);
  }

  return parsed as T;
}

export const api = {
  // Health & Readiness
  health: () => request<HealthResponse>('/health', {}, { skipAuth: true }),
  ready: () => request<ReadyResponse>('/ready', {}, { skipAuth: true }),

  // Authentication
  authConfig: () => request<AuthConfigResponse>('/auth/config', {}, { skipAuth: true }),
  signInGoogle: (body: { id_token?: string; demo_email?: string; demo_name?: string }) =>
    request<AuthSessionResponse>(
      '/auth/google',
      { method: 'POST', body: JSON.stringify(body) },
      { suppressUnauthorizedHook: true },
    ),
  requestPhoneOtp: (phoneNumber: string) =>
    request<PhoneOtpRequestResponse>(
      '/auth/phone/request-otp',
      { method: 'POST', body: JSON.stringify({ phone_number: phoneNumber }) },
      { skipAuth: true },
    ),
  verifyPhoneOtp: (body: { challenge_id: string; phone_number: string; code: string; display_name?: string }) =>
    request<AuthSessionResponse>(
      '/auth/phone/verify-otp',
      { method: 'POST', body: JSON.stringify(body) },
      { suppressUnauthorizedHook: true },
    ),
  me: () => request<AuthUserResponse>('/auth/me'),
  logout: () => request<{ status: string }>('/auth/logout', { method: 'POST' }, { suppressUnauthorizedHook: true }),

  // Control Plane Commands
  sendCommand: (body: {
    text: string;
    source?: 'user_command' | 'ui_button' | 'product_text' | 'agent_output';
    case_id?: string | null;
    mandate_id?: string | null;
  }) => request<CommandResponse>('/commands', { method: 'POST', body: JSON.stringify(body) }),

  // Mandates
  compileMandate: (prompt: string) =>
    request<MandateDraftResponse>('/mandates/compile', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    }),
  confirmMandate: (mandateId: string) =>
    request<MandateResponse>(`/mandates/${encodeURIComponent(mandateId)}/confirm`, { method: 'POST' }),
  amendMandate: (mandateId: string, body: AmendMandateRequest) =>
    request<MandateDraftResponse>(`/mandates/${encodeURIComponent(mandateId)}/amend`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  revokeAllMandates: (reason = 'Kill switch triggered from Mandate UI') =>
    request<RevokeAllResponse>('/mandates/revoke', {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  listMandates: (limit = 50) => request<MandateListResponse>(`/mandates?limit=${limit}`),
  mandatesSchedule: () => request<BryntumTimelineResponse>('/mandates/schedule'),
  getMandate: (mandateId: string, version?: number) =>
    request<MandateResponse>(
      `/mandates/${encodeURIComponent(mandateId)}${version ? `?version=${version}` : ''}`,
    ),

  // Catalog & Shopping
  searchCatalog: (params: { query?: string; verified_only?: boolean; category?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.query) q.set('query', params.query);
    if (params.verified_only) q.set('verified_only', 'true');
    if (params.category) q.set('category', params.category);
    if (params.limit) q.set('limit', String(params.limit));
    return request<CatalogSearchResponse>(`/catalog/search?${q.toString()}`);
  },
  semanticSearchCatalog: (query: string, limit = 12) =>
    request<ElasticSearchResponse>(
      `/catalog/semantic-search?query=${encodeURIComponent(query)}&limit=${limit}`,
    ),
  verifyCatalogUrl: (body: { url?: string; product_id?: string }) =>
    request<KernelVerifyUrlResponse>('/catalog/verify-url', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  shoppingOptions: (mandateId: string, query: string, limit = 5) =>
    request<ShoppingOptionsResponse>('/shopping/options', {
      method: 'POST',
      body: JSON.stringify({ mandate_id: mandateId, query, limit }),
    }),
  runShoppingAgent: (mandateId: string, query: string) =>
    request<ShoppingAgentResponse>('/shopping/agent', {
      method: 'POST',
      body: JSON.stringify({ mandate_id: mandateId, query }),
    }),
  pickShoppingProduct: (mandateId: string, productId: string, quantity = 1, rationale = '') =>
    request<CaseResponse>('/shopping/pick', {
      method: 'POST',
      body: JSON.stringify({ mandate_id: mandateId, product_id: productId, quantity, rationale }),
    }),

  // Cases & Recheck
  proposeCase: (body: ProposeCaseRequest) =>
    request<CaseResponse>('/cases/propose', { method: 'POST', body: JSON.stringify(body) }),
  lockCase: (caseId: string) => request<CaseResponse>(`/cases/${encodeURIComponent(caseId)}/lock`, { method: 'POST' }),
  approveCase: (caseId: string) =>
    request<CaseResponse>(`/cases/${encodeURIComponent(caseId)}/approve`, { method: 'POST' }),
  approveCaseOnly: (caseId: string) =>
    request<CaseResponse>(`/cases/${encodeURIComponent(caseId)}/approve-only`, { method: 'POST' }),
  authorizeCaseOnly: (caseId: string) =>
    request<CaseResponse>(`/cases/${encodeURIComponent(caseId)}/authorize-only`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  captureCaseOnly: (caseId: string) =>
    request<CaseResponse>(`/cases/${encodeURIComponent(caseId)}/capture-only`, { method: 'POST' }),
  holdCase: (caseId: string, durationSeconds = 900) =>
    request<CaseResponse>(`/cases/${encodeURIComponent(caseId)}/hold`, {
      method: 'POST',
      body: JSON.stringify({ duration_seconds: durationSeconds }),
    }),
  resumeCase: (caseId: string) =>
    request<CaseResponse>(`/cases/${encodeURIComponent(caseId)}/resume`, { method: 'POST' }),
  cancelCase: (caseId: string, reason = 'Cancelled by user') =>
    request<CaseResponse>(`/cases/${encodeURIComponent(caseId)}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  recheckCase: (caseId: string) =>
    request<CaseResponse>(`/cases/${encodeURIComponent(caseId)}/recheck`, { method: 'POST' }),
  listCases: (params: { mandate_id?: string; state?: CaseState; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.mandate_id) q.set('mandate_id', params.mandate_id);
    if (params.state) q.set('state', params.state);
    q.set('limit', String(params.limit ?? 50));
    return request<CaseListResponse>(`/cases?${q.toString()}`);
  },
  casesTimeline: () => request<BryntumTimelineResponse>('/cases/timeline'),
  getCase: (caseId: string) => request<CaseResponse>(`/cases/${encodeURIComponent(caseId)}`),
  getCaseWhy: (caseId: string) => request<WhyResponse>(`/cases/${encodeURIComponent(caseId)}/why`),
  getCaseReceipt: (caseId: string, narrative: 'auto' | 'deterministic' | 'llm' = 'auto') =>
    request<IntentReceipt>(`/cases/${encodeURIComponent(caseId)}/receipt?narrative=${narrative}`),
  getCaseSnapshots: (caseId: string) =>
    request<SnapshotListResponse>(`/cases/${encodeURIComponent(caseId)}/snapshots`),
  getCaseDiff: (caseId: string) =>
    request<SnapshotDiffResponse>(`/cases/${encodeURIComponent(caseId)}/diff`),

  // Ledger & Trust
  listLedger: (params: {
    case_id?: string;
    mandate_id?: string;
    event_type?: string;
    startRow?: number;
    endRow?: number;
    sortDir?: 'asc' | 'desc';
  } = {}) => {
    const q = new URLSearchParams();
    if (params.case_id) q.set('case_id', params.case_id);
    if (params.mandate_id) q.set('mandate_id', params.mandate_id);
    if (params.event_type) q.set('event_type', params.event_type);
    if (params.startRow !== undefined) q.set('startRow', String(params.startRow));
    if (params.endRow !== undefined) q.set('endRow', String(params.endRow));
    q.set('sortDir', params.sortDir ?? 'desc');
    return request<LedgerListResponse>(`/ledger?${q.toString()}`);
  },
  searchLedger: (query: string, limit = 25) =>
    request<ElasticSearchResponse>(`/ledger/search?query=${encodeURIComponent(query)}&limit=${limit}`),
  verifyLedger: () => request<LedgerVerificationResult>('/ledger/verify'),
  trustScore: () => request<AgentTrustScore>('/ledger/trust-score'),

  // Integrations & Packs
  integrationsStatus: (probe = false) =>
    request<IntegrationsStatusResponse>(`/integrations/status?probe=${probe}`),
  syncElastic: () => request<ElasticSyncResponse>('/integrations/elastic/sync', { method: 'POST' }),
  triggerRenderWorkflow: (inputArgs: unknown[] = []) =>
    request<RenderWorkflowRunResponse>('/integrations/render/workflows/trigger', {
      method: 'POST',
      body: JSON.stringify({ input_args: inputArgs, run_local_recheck: true }),
    }),
  testZapier: (message = 'Mandate verification ping') =>
    request<ZapierTestResponse>('/integrations/zapier/test', {
      method: 'POST',
      body: JSON.stringify({ event: 'MANDATE_UI_TEST', message }),
    }),
  checkEmailPack: (body: EmailPolicyCheckRequest) =>
    request<EmailPolicyCheckResponse>('/packs/email/check', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // Red-Team Demo Lab
  runDemoScenario: (scenario: string) =>
    request<DemoLabRunResult>(`/demo-lab/run/${encodeURIComponent(scenario)}`, { method: 'POST' }),
  tamperLedgerRow: (seq: number) =>
    request<{ tampered_seq: number; verify: LedgerVerificationResult }>(`/demo-lab/tamper-ledger/${seq}`, {
      method: 'POST',
    }),
  resetDemoLab: () => request<{ status: string }>('/demo-lab/reset', { method: 'POST' }),
};
