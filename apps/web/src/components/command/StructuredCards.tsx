import React from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileCheck2,
  Lock,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ShoppingBag,
  XCircle,
} from 'lucide-react';
import type {
  Case,
  IntentReceipt,
  LedgerEntry,
  Mandate,
  RankedOptionResponse,
  WhyResponse,
} from '../../api/types';
import { useInspector } from '../../context/InspectorContext';
import {
  caseStateTone,
  findingSeverityTone,
  formatDateTime,
  formatMoney,
  mandateStatusTone,
  truncateHash,
} from '../../utils/format';
import { Button, StatusPill } from '../ui/Primitives';

export const MandateDraftCard: React.FC<{
  mandate: Mandate;
  needsConfirm?: boolean;
  onConfirm?: (mandateId: string) => void;
  onConfirmAndShop?: (mandateId: string) => void;
  onFindOptions?: (mandateId: string) => void;
  busy?: boolean;
}> = ({ mandate, needsConfirm, onConfirm, onConfirmAndShop, onFindOptions, busy }) => {
  const { setTarget } = useInspector();
  return (
    <div
      className="surface-card"
      style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
            {mandate.mandate_id} · v{mandate.version}
          </span>
          <StatusPill tone={mandateStatusTone(mandate.status)}>{mandate.status}</StatusPill>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setTarget({ kind: 'mandate', mandate })}>
          Inspect Spec
        </Button>
      </div>

      <div style={{ fontSize: '14px', fontWeight: 500 }}>{mandate.intent_text}</div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: '10px',
          padding: '10px 12px',
          borderRadius: 'var(--radius-sm)',
          background: 'var(--bg-subtle)',
          fontSize: '12px',
        }}
      >
        <div>
          <div style={{ color: 'var(--text-muted)' }}>Spending Limit</div>
          <div className="tabular" style={{ fontSize: '15px', fontWeight: 600, color: 'var(--accent-brass)' }}>
            {formatMoney(mandate.max_total)}
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>Seller Policy</div>
          <div style={{ fontWeight: 500 }}>
            {mandate.require_verified_seller ? 'Verified Only' : 'Any Seller'}
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>Categories</div>
          <div style={{ fontWeight: 500 }}>{mandate.allowed_categories?.join(', ') || 'All Categories'}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>Expires</div>
          <div style={{ fontWeight: 500 }}>{formatDateTime(mandate.expires_at)}</div>
        </div>
      </div>

      {(needsConfirm || mandate.status === 'DRAFT') && (onConfirm || onConfirmAndShop) && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Human confirmation required before agents can shop & recommend items.
          </span>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {onConfirm && (
              <Button
                size="sm"
                variant="secondary"
                loading={busy}
                onClick={() => onConfirm(mandate.mandate_id)}
              >
                Confirm Only
              </Button>
            )}
            {onConfirmAndShop && (
              <Button
                size="sm"
                variant="brass"
                icon={<CheckCircle2 size={14} />}
                loading={busy}
                onClick={() => onConfirmAndShop(mandate.mandate_id)}
              >
                Confirm & Find Recommendations
              </Button>
            )}
          </div>
        </div>
      )}

      {mandate.status === 'ACTIVE' && onFindOptions && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '12px', color: 'var(--status-verified-fg)' }}>
            Mandate is ACTIVE. Ready to search compliant products.
          </span>
          <Button
            size="sm"
            variant="primary"
            icon={<ShoppingBag size={13} />}
            loading={busy}
            onClick={() => onFindOptions(mandate.mandate_id)}
          >
            Find Recommendations (/options)
          </Button>
        </div>
      )}
    </div>
  );
};

export const ShoppingOptionsCard: React.FC<{
  options: RankedOptionResponse[];
  mandateId?: string;
  onPick: (index: number) => void;
  busy?: boolean;
}> = ({ options, mandateId, onPick, busy }) => {
  const { setTarget } = useInspector();
  if (options.length === 0) {
    return (
      <div className="surface-card" style={{ padding: '14px', fontSize: '13px', color: 'var(--text-secondary)' }}>
        No matching catalog options met your mandate constraints.
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '7px', fontSize: '12.5px', fontWeight: 600, color: 'var(--text-secondary)' }}>
        <ShoppingBag size={14} style={{ color: 'var(--accent-brass)' }} />
        <span>Pre-Filtered Catalog Candidates ({options.length})</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: '10px' }}>
        {options.map((opt) => (
          <div
            key={opt.product.product_id}
            className="surface-card"
            style={{ padding: '14px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: '10px' }}
          >
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                <span className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  Option #{opt.index}
                </span>
                <StatusPill tone={opt.product.seller_verified ? 'verified' : 'danger'}>
                  {opt.product.seller_verified ? 'Verified' : 'Unverified'}
                </StatusPill>
              </div>
              <div style={{ fontSize: '13.5px', fontWeight: 600 }}>{opt.product.title}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                {opt.product.seller_name} · {opt.product.in_stock ? 'In Stock' : 'Out of Stock'}
              </div>
              <div className="tabular" style={{ fontSize: '16px', fontWeight: 600, color: 'var(--accent-brass)', marginTop: '8px' }}>
                {formatMoney(opt.product.price)}
              </div>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '6px' }}>{opt.reason}</p>
            </div>
            <div style={{ display: 'flex', gap: '6px', justifyContent: 'space-between' }}>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setTarget({ kind: 'option', option: opt, mandateId })}
              >
                Inspect
              </Button>
              <Button
                size="sm"
                variant="primary"
                loading={busy}
                disabled={!opt.product.in_stock}
                onClick={() => onPick(opt.index)}
              >
                Pick #{opt.index}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export const CaseProposalCard: React.FC<{
  caseData: Case;
  onAction: (action: 'lock' | 'approve' | 'hold' | 'resume' | 'cancel' | 'recheck' | 'why' | 'receipt', caseId: string) => void;
  busy?: boolean;
}> = ({ caseData, onAction, busy }) => {
  const { setTarget } = useInspector();
  const isBlocked = ['BLOCKED', 'FLAGGED', 'CANCELLED', 'EXPIRED'].includes(caseData.state);
  const canApprove = ['CHECKED', 'AWAITING_APPROVAL', 'NEEDS_RECONFIRM'].includes(caseData.state);
  const canLock = caseData.state === 'PROPOSED';
  const canHold = ['CART_LOCKED', 'CHECKED', 'AWAITING_APPROVAL'].includes(caseData.state);
  const canResume = caseData.state === 'HELD';
  const isTerminal = ['VERIFIED', 'CANCELLED', 'BLOCKED', 'EXPIRED'].includes(caseData.state);

  return (
    <div
      className="surface-card"
      style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
            {caseData.case_id}
          </span>
          <StatusPill tone={caseStateTone(caseData.state)}>{caseData.state}</StatusPill>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setTarget({ kind: 'case', caseData })}>
          Open Timeline
        </Button>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '12px', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: '14.5px', fontWeight: 600 }}>{caseData.proposal.title}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
            Qty {caseData.proposal.quantity} · Seller {caseData.proposal.claimed_seller_id} · Payee{' '}
            <span className="mono">{caseData.proposal.claimed_payee_id}</span>
          </div>
        </div>
        <div className="tabular" style={{ fontSize: '18px', fontWeight: 600, color: 'var(--accent-brass)' }}>
          {formatMoney(caseData.proposal.claimed_total)}
        </div>
      </div>

      {caseData.last_findings.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
          {caseData.last_findings.slice(0, 4).map((f, i) => (
            <div
              key={`${f.code}-${i}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '8px',
                padding: '6px 10px',
                borderRadius: 'var(--radius-xs)',
                background: 'var(--bg-subtle)',
                fontSize: '12px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                {f.severity === 'block' ? (
                  <ShieldAlert size={13} style={{ color: 'var(--status-danger-fg)' }} />
                ) : f.severity === 'warn' ? (
                  <AlertTriangle size={13} style={{ color: 'var(--status-warn-fg)' }} />
                ) : (
                  <ShieldCheck size={13} style={{ color: 'var(--status-verified-fg)' }} />
                )}
                <span className="mono" style={{ fontSize: '11px', fontWeight: 600 }}>{f.code}</span>
                <span style={{ color: 'var(--text-secondary)' }}>{f.explanation || f.message}</span>
              </div>
              <StatusPill tone={findingSeverityTone(f.severity)}>{f.severity}</StatusPill>
            </div>
          ))}
        </div>
      )}

      {isBlocked && (
        <div style={{ fontSize: '12px', color: 'var(--status-danger-fg)' }}>
          Execution halted fail-closed by Mandate Core. Inspect findings via /why or review the ledger proof.
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', paddingTop: '4px', borderTop: '1px solid var(--border-subtle)' }}>
        {canLock && (
          <Button size="sm" variant="primary" icon={<Lock size={13} />} loading={busy} onClick={() => onAction('lock', caseData.case_id)}>
            Lock & Check
          </Button>
        )}
        {canApprove && (
          <Button size="sm" variant="brass" icon={<CheckCircle2 size={13} />} loading={busy} onClick={() => onAction('approve', caseData.case_id)}>
            Approve & Pay (/approve)
          </Button>
        )}
        {canHold && (
          <Button size="sm" variant="secondary" icon={<PauseCircle size={13} />} loading={busy} onClick={() => onAction('hold', caseData.case_id)}>
            Hold 15m
          </Button>
        )}
        {canResume && (
          <Button size="sm" variant="primary" icon={<PlayCircle size={13} />} loading={busy} onClick={() => onAction('resume', caseData.case_id)}>
            Resume
          </Button>
        )}
        {!isTerminal && (
          <>
            <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} loading={busy} onClick={() => onAction('recheck', caseData.case_id)}>
              Recheck
            </Button>
            <Button size="sm" variant="danger" icon={<XCircle size={13} />} loading={busy} onClick={() => onAction('cancel', caseData.case_id)}>
              Cancel
            </Button>
          </>
        )}
        <Button size="sm" variant="ghost" onClick={() => onAction('why', caseData.case_id)}>
          /why
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onAction('receipt', caseData.case_id)}>
          /receipt
        </Button>
      </div>
    </div>
  );
};

export const SecurityEventCard: React.FC<{
  why?: WhyResponse;
  title?: string;
  lines?: string[];
  tone?: 'danger' | 'warn' | 'verified' | 'neutral';
}> = ({ why, title, lines, tone = 'warn' }) => (
  <div className="surface-card" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', fontSize: '13.5px', fontWeight: 600 }}>
        <ShieldAlert size={15} style={{ color: 'var(--accent-brass)' }} />
        {title || (why ? `Policy Diagnostic · ${why.case_id}` : 'Security Event')}
      </span>
      <StatusPill tone={why ? caseStateTone(why.state) : tone}>{why ? why.state : 'SECURITY'}</StatusPill>
    </div>
    {why && (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
        {why.plain_english_reasons.map((r, idx) => (
          <div key={idx}>• {r}</div>
        ))}
      </div>
    )}
    {lines && lines.length > 0 && (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12.5px', color: 'var(--text-secondary)' }}>
        {lines.map((l, i) => (
          <div key={i}>{l}</div>
        ))}
      </div>
    )}
  </div>
);

export const IntentReceiptCard: React.FC<{ receipt: IntentReceipt }> = ({ receipt }) => {
  const f = receipt.facts;
  return (
    <div className="surface-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', fontWeight: 600, fontSize: '13.5px' }}>
          <FileCheck2 size={15} style={{ color: 'var(--accent-brass)' }} />
          Canonical Intent Receipt
        </span>
        <div style={{ display: 'flex', gap: '6px' }}>
          <StatusPill tone={caseStateTone(f.state)}>{f.state}</StatusPill>
          <StatusPill tone="neutral">{receipt.narrative_source}</StatusPill>
        </div>
      </div>

      <p style={{ fontSize: '13px', color: 'var(--text-primary)' }}>{receipt.narrative}</p>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
          gap: '8px',
          padding: '10px 12px',
          background: 'var(--bg-subtle)',
          borderRadius: 'var(--radius-sm)',
          fontSize: '12px',
        }}
      >
        <div>
          <div style={{ color: 'var(--text-muted)' }}>Amount</div>
          <div className="tabular" style={{ fontWeight: 600 }}>
            {f.total_amount} {f.currency} (×{f.quantity})
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>Seller / Payee</div>
          <div className="mono">{f.seller_id} / {f.payee_id}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>PayPal Order</div>
          <div className="mono">{f.paypal_order_id || '—'}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>Ledger Seq</div>
          <div className="mono">#{f.latest_ledger_seq ?? '—'}</div>
        </div>
      </div>

      <div className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)', wordBreak: 'break-all' }}>
        SHA-256: {receipt.receipt_hash}
      </div>
    </div>
  );
};

export const LedgerSliceCard: React.FC<{ entries: LedgerEntry[]; totalCount?: number }> = ({
  entries,
  totalCount,
}) => {
  const { setTarget } = useInspector();
  return (
    <div className="surface-card" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 600, fontSize: '13px' }}>
          Hash-Chained Ledger ({entries.length}
          {totalCount !== undefined ? ` of ${totalCount}` : ''})
        </span>
        <StatusPill tone="verified">SHA-256</StatusPill>
      </div>
      {entries.length === 0 ? (
        <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)' }}>No ledger entries recorded yet.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
          {entries.slice(0, 8).map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setTarget({ kind: 'ledger', entry })}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '10px',
                padding: '7px 10px',
                borderRadius: 'var(--radius-xs)',
                border: '1px solid var(--border-subtle)',
                background: 'var(--bg-subtle)',
                cursor: 'pointer',
                textAlign: 'left',
                fontSize: '12px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                <span className="mono" style={{ color: 'var(--accent-brass)', fontWeight: 600 }}>#{entry.seq}</span>
                <span style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {entry.event_type}
                </span>
              </div>
              <div className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                <Clock size={11} />
                {truncateHash(entry.hash, 8, 6)}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
