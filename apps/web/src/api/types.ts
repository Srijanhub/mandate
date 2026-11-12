import type { components } from './generated';

type Schemas = components['schemas'];

export type Money = Schemas['Money'];
export type Finding = Schemas['Finding'];
export type FindingSeverity = Schemas['FindingSeverity'];
export type Decision = Schemas['Decision'];
export type MandateStatus = Schemas['MandateStatus'];
export type Mandate = Schemas['Mandate'] & {
  mandate_id: string;
  version: number;
  status: MandateStatus;
  created_at: string;
  updated_at: string;
};
export type MandateDraftResponse = Omit<Schemas['MandateDraftResponse'], 'mandate'> & {
  mandate: Mandate;
};
export type MandateResponse = Omit<Schemas['MandateResponse'], 'mandate'> & {
  mandate: Mandate;
};
export type MandateListResponse = {
  mandates: Mandate[];
};
export type CompileMandateRequest = Schemas['CompileMandateRequest'];
export type AmendMandateRequest = Schemas['AmendMandateRequest'];
export type RevokeAllResponse = Schemas['RevokeAllResponse'];

export type Product = Schemas['Product'];
export type Proposal = Schemas['Proposal'];
export type CaseState = Schemas['CaseState'];
export type Case = Schemas['Case'] & {
  case_id: string;
  state: CaseState;
  last_findings: Finding[];
  created_at: string;
  updated_at: string;
};
export type CaseSnapshot = Schemas['CaseSnapshot'];
export type CaseResponse = { case: Case };
export type CaseListResponse = { cases: Case[] };
export type WhyResponse = Schemas['WhyResponse'];
export type SnapshotListResponse = Schemas['SnapshotListResponse'];
export type SnapshotDiffResponse = Schemas['SnapshotDiffResponse'];
export type ProposeCaseRequest = Schemas['ProposeCaseRequest'];

export type RankedOptionResponse = Schemas['RankedOptionResponse'];
export type ShoppingOptionsResponse = Schemas['ShoppingOptionsResponse'];
export type ShoppingAgentResponse = Omit<Schemas['ShoppingAgentResponse'], 'case'> & {
  case?: Case | null;
};
export type CatalogSearchResponse = Schemas['CatalogSearchResponse'];
export type ElasticSearchResponse = Schemas['ElasticSearchResponse'];
export type ElasticSearchHit = Schemas['ElasticSearchHit'];
export type KernelVerifyUrlResponse = Schemas['KernelVerifyUrlResponse'];

export type LedgerEntry = Schemas['LedgerEntry'] & {
  id: string;
  created_at: string;
};
export type LedgerListResponse = Omit<Schemas['LedgerListResponse'], 'rows'> & {
  rows: LedgerEntry[];
};
export type LedgerVerificationResult = Schemas['LedgerVerificationResult'];
export type AgentTrustScore = Schemas['AgentTrustScore'];

export type IntentReceipt = Schemas['IntentReceipt'];
export type IntentReceiptFacts = Schemas['IntentReceiptFacts'];

export type ReadyResponse = Schemas['ReadyResponse'];
export type HealthResponse = Schemas['HealthResponse'];
export type IntegrationsStatusResponse = Schemas['IntegrationsStatusResponse'];
export type IntegrationServiceStatus = Schemas['IntegrationServiceStatus'];
export type RenderWorkflowRunResponse = Schemas['RenderWorkflowRunResponse'];
export type ElasticSyncResponse = Schemas['ElasticSyncResponse'];
export type ZapierTestResponse = Schemas['ZapierTestResponse'];

export type BryntumTimelineResponse = Schemas['BryntumTimelineResponse'];
export type EmailPolicyCheckRequest = Schemas['EmailPolicyCheckRequest'];
export type EmailPolicyCheckResponse = Schemas['EmailPolicyCheckResponse'];

export type AuthConfigResponse = Schemas['AuthConfigResponse'];
export type AuthUserResponse = Schemas['AuthUserResponse'] & {
  auth_providers: string[];
};
export type AuthSessionResponse = Omit<Schemas['AuthSessionResponse'], 'user'> & {
  user: AuthUserResponse;
};
export type PhoneOtpRequestResponse = Schemas['PhoneOtpRequestResponse'];

export interface CommandResponse {
  is_command: boolean;
  command?: string;
  action?: string;
  mandate?: Mandate;
  needs_confirm?: boolean;
  mandate_id?: string;
  options?: RankedOptionResponse[];
  message?: string;
  case?: Case;
  receipt?: IntentReceipt;
  commands?: Array<{ name: string; description: string }>;
  entries?: LedgerEntry[];
  total_count?: number;
  revoked_mandates?: string[];
  cancelled_cases?: string[];
  voided_authorizations?: string[];
  // WhyResponse fields when /why is called
  case_id?: string;
  state?: string;
  plain_english_reasons?: string[];
  blocking_findings?: Finding[];
  warning_findings?: Finding[];
  passed_checks?: Finding[];
  snapshot_diff?: Finding[];
}

export interface DemoLabRunResult {
  scenario: string;
  case_id?: string;
  case_state?: string;
  sanitized_preview?: string;
  why?: WhyResponse;
  receipt?: IntentReceipt;
  control_plane_blocked_product_command?: boolean;
  revoked_mandates?: string[];
  cancelled_cases?: string[];
  voided_authorizations?: string[];
  paypal_order_status?: string;
  blocked_reason?: string;
  tampered_seq?: number;
  verify?: LedgerVerificationResult;
  first?: Record<string, unknown>;
  second?: Record<string, unknown>;
  [key: string]: unknown;
}
