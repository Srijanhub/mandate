import React, { useEffect, useState } from 'react';
import {
  CheckCircle2,
  Clock,
  FileCheck2,
  GitCompare,
  Hash,
  Lock,
  ShieldCheck,
  ShieldX,
  X,
} from 'lucide-react';
import { api } from '../../api/client';
import type { Case, CaseSnapshot, IntentReceipt, WhyResponse } from '../../api/types';
import { useInspector } from '../../context/InspectorContext';
import {
  caseStateTone,
  findingSeverityTone,
  formatDateTime,
  formatMoney,
  mandateStatusTone,
  truncateHash,
} from '../../utils/format';
import { StatusPill } from '../ui/Primitives';

const CHECKPOINTS = [
  { code: 'C1', label: 'Proposal Ingested', states: ['PROPOSED', 'CART_LOCKED', 'CHECKED', 'AWAITING_APPROVAL', 'APPROVED', 'AUTHORIZED', 'CAPTURED', 'VERIFIED'] },
  { code: 'C2', label: 'Cart Locked', states: ['CART_LOCKED', 'CHECKED', 'AWAITING_APPROVAL', 'APPROVED', 'AUTHORIZED', 'CAPTURED', 'VERIFIED'] },
  { code: 'C3', label: 'Pre-Approval Check', states: ['CHECKED', 'AWAITING_APPROVAL', 'APPROVED', 'AUTHORIZED', 'CAPTURED', 'VERIFIED'] },
  { code: 'C4', label: 'Human Approval', states: ['APPROVED', 'AUTHORIZED', 'CAPTURED', 'VERIFIED'] },
  { code: 'C5', label: 'PayPal Auth & Pre-Capture', states: ['AUTHORIZED', 'CAPTURED', 'VERIFIED'] },
  { code: 'C6', label: 'ProofGuard Verified', states: ['VERIFIED'] },
];

const CaseInspectorView: React.FC<{ caseData: Case }> = ({ caseData }) => {
  const [why, setWhy] = useState<WhyResponse | null>(null);
  const [receipt, setReceipt] = useState<IntentReceipt | null>(null);
  const [snapshots, setSnapshots] = useState<CaseSnapshot[]>([]);

  useEffect(() => {
    let active = true;
    setWhy(null);
    setReceipt(null);
    setSnapshots([]);

    Promise.allSettled([
      api.getCaseWhy(caseData.case_id),
      api.getCaseReceipt(caseData.case_id, 'deterministic'),
      api.getCaseSnapshots(caseData.case_id),
    ]).then(([w, r, s]) => {
      if (!active) return;
      if (w.status === 'fulfilled') setWhy(w.value);
      if (r.status === 'fulfilled') setReceipt(r.value);
      if (s.status === 'fulfilled') setSnapshots(s.value.snapshots);
    });
    return () => {
      active = false;
    };
  }, [caseData.case_id, caseData.state, caseData.updated_at]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
          <span className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
            {caseData.case_id}
          </span>
          <StatusPill tone={caseStateTone(caseData.state)}>{caseData.state}</StatusPill>
        </div>
        <h3 style={{ fontSize: '15px', fontWeight: 600, marginTop: '6px' }}>{caseData.proposal.title}</h3>
        <div className="tabular" style={{ fontSize: '18px', fontWeight: 600, color: 'var(--accent-brass)', marginTop: '4px' }}>
          {formatMoney(caseData.proposal.claimed_total)}
        </div>
      </div>

      {/* Checkpoint Timeline */}
      <div className="surface-elevated" style={{ padding: '12px 14px' }}>
        <div className="mono" style={{ fontSize: '10.5px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '10px' }}>
          Checkpoint Progression (C1–C6)
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
          {CHECKPOINTS.map((cp) => {
            const reached = cp.states.includes(caseData.state);
            const isHalted = ['BLOCKED', 'FLAGGED', 'CANCELLED', 'NEEDS_RECONFIRM'].includes(caseData.state);
            return (
              <div key={cp.code} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12.5px' }}>
                <span
                  className="mono"
                  style={{
                    width: '26px',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: reached ? 'var(--status-verified-fg)' : isHalted ? 'var(--status-warn-fg)' : 'var(--text-muted)',
                  }}
                >
                  {cp.code}
                </span>
                {reached ? (
                  <CheckCircle2 size={13} style={{ color: 'var(--status-verified-fg)' }} />
                ) : (
                  <Clock size={13} style={{ color: 'var(--text-muted)' }} />
                )}
                <span style={{ color: reached ? 'var(--text-primary)' : 'var(--text-secondary)' }}>{cp.label}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* PayPal & Snapshots */}
      <div className="surface-elevated" style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '7px', fontSize: '12.5px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Seller ID</span>
          <span className="mono">{caseData.proposal.claimed_seller_id}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Payee ID</span>
          <span className="mono">{caseData.proposal.claimed_payee_id}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>PayPal Order</span>
          <span className="mono">{caseData.paypal_order_id || 'Pending'}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-secondary)' }}>Snapshots Recorded</span>
          <span className="mono">{snapshots.length}</span>
        </div>
      </div>

      {/* Plain-English Policy Reasons */}
      {why && why.plain_english_reasons.length > 0 && (
        <div className="surface-elevated" style={{ padding: '12px 14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 600, marginBottom: '8px' }}>
            <GitCompare size={14} style={{ color: 'var(--accent-brass)' }} />
            <span>Verification Findings (/why)</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {[...why.blocking_findings, ...why.warning_findings, ...why.passed_checks.slice(0, 3)].map((f, idx) => (
              <div
                key={`${f.code}-${idx}`}
                style={{
                  padding: '7px 9px',
                  borderRadius: 'var(--radius-xs)',
                  background: 'var(--bg-subtle)',
                  fontSize: '12px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                  <span className="mono" style={{ fontSize: '11px', fontWeight: 600 }}>{f.code}</span>
                  <StatusPill tone={findingSeverityTone(f.severity)}>{f.severity}</StatusPill>
                </div>
                <div style={{ color: 'var(--text-secondary)' }}>{f.explanation || f.message}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Intent Receipt Hash */}
      {receipt && (
        <div className="surface-elevated" style={{ padding: '12px 14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 600 }}>
              <FileCheck2 size={14} style={{ color: 'var(--accent-brass)' }} />
              Canonical Intent Receipt
            </span>
            <StatusPill tone="verified">SHA-256</StatusPill>
          </div>
          <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '8px' }}>{receipt.narrative}</p>
          <div className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)', wordBreak: 'break-all' }}>
            {receipt.receipt_hash}
          </div>
        </div>
      )}
    </div>
  );
};

export const ContextualInspector: React.FC<{ onCloseMobile?: () => void }> = ({ onCloseMobile }) => {
  const { target, clearTarget } = useInspector();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: '12px', borderBottom: '1px solid var(--border-subtle)' }}>
        <div>
          <div className="mono" style={{ fontSize: '10.5px', color: 'var(--accent-brass)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Contextual Intelligence
          </div>
          <div style={{ fontSize: '14px', fontWeight: 600, marginTop: '2px' }}>
            {target.kind === 'mandate'
              ? 'Mandate Policy Spec'
              : target.kind === 'option'
                ? 'Candidate & Risk Check'
                : target.kind === 'case'
                  ? 'Case Verification'
                  : target.kind === 'ledger'
                    ? 'Ledger Proof Record'
                    : 'Control Summary'}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          {target.kind !== 'none' && (
            <button
              type="button"
              onClick={clearTarget}
              title="Reset context"
              style={{
                background: 'transparent',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-xs)',
                padding: '4px 7px',
                fontSize: '11px',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
              }}
            >
              Clear
            </button>
          )}
          {onCloseMobile && (
            <button
              type="button"
              onClick={onCloseMobile}
              aria-label="Close panel"
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                padding: '4px',
              }}
            >
              <X size={16} />
            </button>
          )}
        </div>
      </div>

      {target.kind === 'mandate' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
              {target.mandate.mandate_id} · v{target.mandate.version}
            </span>
            <StatusPill tone={mandateStatusTone(target.mandate.status)}>{target.mandate.status}</StatusPill>
          </div>
          <p style={{ fontSize: '13.5px', fontWeight: 500 }}>{target.mandate.intent_text}</p>
          <div className="surface-elevated" style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12.5px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Max Cap</span>
              <span className="tabular" style={{ fontWeight: 600, color: 'var(--accent-brass)' }}>
                {formatMoney(target.mandate.max_total)}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Spent Total</span>
              <span className="tabular">{formatMoney(target.mandate.spent_total)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Daily / Weekly Cap</span>
              <span className="tabular">
                {target.mandate.max_spend_per_day ? formatMoney(target.mandate.max_spend_per_day) : '—'} /{' '}
                {target.mandate.max_spend_per_week ? formatMoney(target.mandate.max_spend_per_week) : '—'}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Verified Sellers Only</span>
              <span>{target.mandate.require_verified_seller ? 'Enforced' : 'Optional'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Allowed Categories</span>
              <span>{target.mandate.allowed_categories?.join(', ') || 'Any'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Expires</span>
              <span>{formatDateTime(target.mandate.expires_at)}</span>
            </div>
          </div>
        </div>
      )}

      {target.kind === 'option' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
              Option #{target.option.index} · {target.option.product.product_id}
            </span>
            <StatusPill tone={target.option.product.seller_verified ? 'verified' : 'danger'}>
              {target.option.product.seller_verified ? 'Verified Seller' : 'Unverified'}
            </StatusPill>
          </div>
          <h3 style={{ fontSize: '15px', fontWeight: 600 }}>{target.option.product.title}</h3>
          <div className="tabular" style={{ fontSize: '18px', fontWeight: 600, color: 'var(--accent-brass)' }}>
            {formatMoney(target.option.product.price)}
          </div>
          <div className="surface-elevated" style={{ padding: '12px 14px', fontSize: '12.5px', display: 'flex', flexDirection: 'column', gap: '7px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Merchant</span>
              <span>{target.option.product.seller_name}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Payee ID</span>
              <span className="mono">{target.option.product.payee_id}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Stock</span>
              <span>{target.option.product.in_stock ? 'In Stock' : 'Out of Stock'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Match Score</span>
              <span className="mono">{target.option.deterministic_score.toFixed(2)}</span>
            </div>
          </div>
          <div className="surface-elevated" style={{ padding: '12px 14px', fontSize: '12px', color: 'var(--text-secondary)' }}>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
              Sanitized Description
            </div>
            {target.option.sanitized_description}
          </div>
        </div>
      )}

      {target.kind === 'case' && <CaseInspectorView caseData={target.caseData} />}

      {target.kind === 'ledger' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="mono" style={{ fontSize: '12px', fontWeight: 600 }}>
              SEQ #{target.entry.seq}
            </span>
            <StatusPill tone="neutral">{target.entry.event_type}</StatusPill>
          </div>
          <div className="surface-elevated" style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px' }}>
            <div>
              <div style={{ color: 'var(--text-muted)', marginBottom: '2px' }}>Entry Hash</div>
              <div className="mono" style={{ wordBreak: 'break-all' }}>{target.entry.hash}</div>
            </div>
            <div>
              <div style={{ color: 'var(--text-muted)', marginBottom: '2px' }}>Previous Hash</div>
              <div className="mono" style={{ color: 'var(--text-secondary)' }}>{truncateHash(target.entry.prev_hash, 14, 10)}</div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Actor</span>
              <span className="mono">{target.entry.actor}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Timestamp</span>
              <span>{formatDateTime(target.entry.created_at)}</span>
            </div>
          </div>
          <div className="surface-elevated" style={{ padding: '12px 14px' }}>
            <div className="mono" style={{ fontSize: '10.5px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
              Signed Payload
            </div>
            <pre className="mono" style={{ fontSize: '11.5px', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-secondary)' }}>
              {JSON.stringify(target.entry.payload, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {target.kind === 'none' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div className="surface-elevated" style={{ padding: '14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, fontSize: '13px', marginBottom: '6px' }}>
              <Lock size={14} style={{ color: 'var(--accent-brass)' }} />
              <span>Fail-Closed Enforcement</span>
            </div>
            <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)' }}>
              Select any mandate, shopping option, checkout case, or ledger record in the workspace to inspect real-time verification checks, snapshots, and SHA-256 proofs here.
            </p>
          </div>

          <div className="surface-elevated" style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
              <ShieldCheck size={14} style={{ color: 'var(--status-verified-fg)' }} />
              <span>Pre-LLM slash command boundary</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
              <Hash size={14} style={{ color: 'var(--accent-brass)' }} />
              <span>SHA-256 chain & Intent Receipts</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
              <ShieldX size={14} style={{ color: 'var(--status-danger-fg)' }} />
              <span>Automatic PayPal void on C5 drift</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
