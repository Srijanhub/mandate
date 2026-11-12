import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, FileCheck2, Mail, RefreshCw, ShieldAlert, ShieldCheck } from 'lucide-react';
import { api, MandateApiError } from '../api/client';
import type {
  AgentTrustScore,
  Case,
  EmailPolicyCheckResponse,
  IntentReceipt,
  LedgerVerificationResult,
} from '../api/types';
import { IntentReceiptCard } from '../components/command/StructuredCards';
import { Button, ErrorBanner, SectionHeader, StatusPill } from '../components/ui/Primitives';

export const TrustPage: React.FC = () => {
  const [verify, setVerify] = useState<LedgerVerificationResult | null>(null);
  const [trust, setTrust] = useState<AgentTrustScore | null>(null);
  const [cases, setCases] = useState<Case[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState('');
  const [receipt, setReceipt] = useState<IntentReceipt | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Domain-agnostic Email Policy Pack state
  const [emailSubject, setEmailSubject] = useState('Q4 Vendor Receipt Confirmation');
  const [emailRecipients, setEmailRecipients] = useState('finance@company.com, ops@company.com');
  const [allowedDomains, setAllowedDomains] = useState('company.com');
  const [maxRecipients, setMaxRecipients] = useState(3);
  const [emailResult, setEmailResult] = useState<EmailPolicyCheckResponse | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [vRes, tRes, cRes] = await Promise.all([
        api.verifyLedger(),
        api.trustScore(),
        api.listCases({ limit: 30 }),
      ]);
      setVerify(vRes);
      setTrust(tRes);
      setCases(cRes.cases);
      if (cRes.cases.length > 0) {
        const cid = cRes.cases[0].case_id;
        setSelectedCaseId(cid);
        try {
          setReceipt(await api.getCaseReceipt(cid, 'auto'));
        } catch {
          setReceipt(null);
        }
      }
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Failed to load verification metrics');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleLoadReceipt = async (cid: string) => {
    setSelectedCaseId(cid);
    if (!cid) return;
    setLoading(true);
    setError(null);
    try {
      setReceipt(await api.getCaseReceipt(cid, 'auto'));
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Could not fetch receipt');
    } finally {
      setLoading(false);
    }
  };

  const handleCheckEmailPolicy = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const recipients = emailRecipients
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const domains = allowedDomains
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await api.checkEmailPack({
        subject: emailSubject.trim(),
        recipients,
        body_preview: 'Verified policy test',
        max_recipients: maxRecipients,
        allowed_recipient_domains: domains,
      });
      setEmailResult(res);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Email policy check failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <SectionHeader
        eyebrow="Cryptographic Proof & Core Reusability"
        title="Trust & Verification"
        subtitle="Verify the entire ledger chain, inspect deterministic Intent Receipts, and prove policy-engine reuse on non-shopping domains."
        right={
          <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} loading={loading} onClick={load}>
            Re-Verify
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px' }}>
        {/* Chain Proof */}
        <div className="surface-card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', fontWeight: 600 }}>
              <ShieldCheck size={16} style={{ color: 'var(--accent-brass)' }} />
              Cryptographic Hash Chain
            </span>
            {verify && (
              <StatusPill tone={verify.valid ? 'verified' : 'danger'}>
                {verify.valid ? 'VALID' : 'BROKEN'}
              </StatusPill>
            )}
          </div>
          {verify && (
            <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div>Verified Entries: {verify.verified_entries} / {verify.total_entries}</div>
              <div>
                Genesis Hash: <span className="mono">{verify.genesis_hash}</span>
              </div>
              <div style={{ wordBreak: 'break-all' }}>
                Latest Hash: <span className="mono">{verify.latest_hash || '—'}</span>
              </div>
              {!verify.valid && (
                <div style={{ color: 'var(--status-danger-fg)' }}>
                  Tampered Sequence #{verify.first_broken_seq}: {verify.broken_reason}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Trust Breakdown */}
        <div className="surface-card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 600 }}>Agent Compliance & Trust</span>
            <span className="tabular" style={{ fontSize: '20px', fontWeight: 600, color: 'var(--accent-brass)' }}>
              {trust ? `${trust.trust_score_percent.toFixed(1)}%` : '—'}
            </span>
          </div>
          {trust && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
              <div>Total Cases: <strong style={{ color: 'var(--text-primary)' }}>{trust.total_cases}</strong></div>
              <div>Clean Verified: <strong style={{ color: 'var(--status-verified-fg)' }}>{trust.clean_verified_cases}</strong></div>
              <div>Blocked / Flagged: <strong style={{ color: 'var(--status-danger-fg)' }}>{trust.blocked_or_flagged_cases}</strong></div>
              <div>Avg Verify Time: <strong style={{ color: 'var(--text-primary)' }}>{trust.avg_time_to_verify_seconds?.toFixed(1) ?? '—'}s</strong></div>
            </div>
          )}
        </div>
      </div>

      {/* Intent Receipt Inspector */}
      <div className="surface-card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', fontWeight: 600 }}>
            <FileCheck2 size={16} style={{ color: 'var(--accent-brass)' }} />
            Canonical Intent Receipt Viewer (`GET /cases/&#123;id&#125;/receipt`)
          </div>
          <select
            value={selectedCaseId}
            onChange={(e) => void handleLoadReceipt(e.target.value)}
            style={{
              padding: '7px 10px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-subtle)',
              background: 'var(--bg-main)',
              fontSize: '12.5px',
            }}
          >
            {cases.length === 0 && <option value="">No cases available</option>}
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {c.case_id} — {c.proposal.title} ({c.state})
              </option>
            ))}
          </select>
        </div>
        {receipt ? (
          <IntentReceiptCard receipt={receipt} />
        ) : (
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
            Select a case above to compute and verify its SHA-256 Intent Receipt.
          </p>
        )}
      </div>

      {/* Domain-Agnostic Policy Pack Tester */}
      <div className="surface-card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
          <div>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', fontWeight: 600 }}>
              <Mail size={15} style={{ color: 'var(--accent-brass)' }} />
              Domain-Agnostic Core Proof — Email Agent Policy Pack (`POST /packs/email/check`)
            </div>
            <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '3px' }}>
              Evaluates `max_recipients` and `allowed_recipient_domains` using the exact same `mandate_core` Rule Engine & Ledger.
            </p>
          </div>
        </div>

        <form onSubmit={handleCheckEmailPolicy} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '10px', alignItems: 'end' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Email Subject</span>
            <input
              type="text"
              value={emailSubject}
              onChange={(e) => setEmailSubject(e.target.value)}
              style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', background: 'var(--bg-main)' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Recipients (comma-separated)</span>
            <input
              type="text"
              value={emailRecipients}
              onChange={(e) => setEmailRecipients(e.target.value)}
              className="mono"
              style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', background: 'var(--bg-main)' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Allowed Domains</span>
            <input
              type="text"
              value={allowedDomains}
              onChange={(e) => setAllowedDomains(e.target.value)}
              className="mono"
              style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', background: 'var(--bg-main)' }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Max Recipients</span>
            <input
              type="number"
              min={1}
              value={maxRecipients}
              onChange={(e) => setMaxRecipients(Number(e.target.value) || 1)}
              style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', background: 'var(--bg-main)' }}
            />
          </label>
          <Button type="submit" variant="brass" loading={loading}>
            Evaluate Policy
          </Button>
        </form>

        {emailResult && (
          <div className="surface-elevated" style={{ padding: '12px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
            <div>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontWeight: 600, fontSize: '13px' }}>
                {emailResult.decision.allow ? (
                  <CheckCircle2 size={14} style={{ color: 'var(--status-verified-fg)' }} />
                ) : (
                  <ShieldAlert size={14} style={{ color: 'var(--status-danger-fg)' }} />
                )}
                {emailResult.decision.plain_english_summary}
              </div>
              <div className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '3px' }}>
                Recorded at ledger seq #{emailResult.ledger_seq}
              </div>
            </div>
            <StatusPill tone={emailResult.decision.allow ? 'verified' : 'danger'}>
              {emailResult.decision.allow ? 'ALLOW' : 'BLOCK'}
            </StatusPill>
          </div>
        )}
      </div>
    </div>
  );
};
