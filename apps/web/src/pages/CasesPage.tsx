import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  CheckCircle2,
  FileCheck2,
  Lock,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  XCircle,
} from 'lucide-react';
import { api, MandateApiError } from '../api/client';
import type { Case, CaseState } from '../api/types';
import { Button, ConfirmModal, EmptyState, ErrorBanner, SectionHeader, StatusPill } from '../components/ui/Primitives';
import { useInspector } from '../context/InspectorContext';
import { caseStateTone, formatDateTime, formatMoney } from '../utils/format';

export const CasesPage: React.FC = () => {
  const { setTarget } = useInspector();
  const [cases, setCases] = useState<Case[]>([]);
  const [stateFilter, setStateFilter] = useState<CaseState | 'ALL'>('ALL');
  const [loading, setLoading] = useState(true);
  const [busyCaseId, setBusyCaseId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmApproveId, setConfirmApproveId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listCases({
        state: stateFilter === 'ALL' ? undefined : stateFilter,
        limit: 100,
      });
      setCases(res.cases);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Failed to load cases');
    } finally {
      setLoading(false);
    }
  }, [stateFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const mutate = async (caseId: string, fn: () => Promise<{ case: Case }>) => {
    setBusyCaseId(caseId);
    setError(null);
    try {
      const res = await fn();
      setTarget({ kind: 'case', caseData: res.case });
      await load();
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Case transition failed');
    } finally {
      setBusyCaseId(null);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <SectionHeader
        eyebrow="C1–C8 Enforcement Lifecycle"
        title="Cases & Transactions"
        subtitle="Inspect purchase proposals, execute PayPal Order v2 approvals/holds, view snapshot diffs, and verify Intent Receipts."
        right={
          <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} loading={loading} onClick={load}>
            Refresh
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
        {(['ALL', 'PROPOSED', 'CART_LOCKED', 'AWAITING_APPROVAL', 'HELD', 'VERIFIED', 'BLOCKED', 'NEEDS_RECONFIRM', 'CANCELLED'] as const).map(
          (st) => (
            <Button
              key={st}
              size="sm"
              variant={stateFilter === st ? 'primary' : 'secondary'}
              onClick={() => setStateFilter(st)}
            >
              {st}
            </Button>
          ),
        )}
      </div>

      {cases.length === 0 ? (
        <EmptyState
          icon={<Activity size={18} />}
          title="No cases found"
          description="Use Command Centre (/options -> /pick 1) or Shopping & Proposals to propose a purchase case."
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {cases.map((c) => {
            const busy = busyCaseId === c.case_id;
            const isTerminal = ['VERIFIED', 'CANCELLED', 'BLOCKED', 'EXPIRED'].includes(c.state);
            const canApprove = ['CHECKED', 'AWAITING_APPROVAL', 'NEEDS_RECONFIRM'].includes(c.state);
            return (
              <div
                key={c.case_id}
                className="surface-card"
                onClick={() => setTarget({ kind: 'case', caseData: c })}
                style={{ padding: '16px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: '12px' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className="mono" style={{ fontSize: '12px', fontWeight: 600 }}>
                      {c.case_id}
                    </span>
                    <StatusPill tone={caseStateTone(c.state)}>{c.state}</StatusPill>
                    <span className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      Mandate {c.mandate_id} v{c.mandate_version}
                    </span>
                  </div>
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Updated {formatDateTime(c.updated_at)}
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: '12px' }}>
                  <div>
                    <div style={{ fontSize: '15px', fontWeight: 600 }}>{c.proposal.title}</div>
                    <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      Seller {c.proposal.claimed_seller_id} · Payee{' '}
                      <span className="mono">{c.proposal.claimed_payee_id}</span> · PayPal Order{' '}
                      <span className="mono">{c.paypal_order_id || 'Pending'}</span>
                    </div>
                  </div>
                  <div className="tabular" style={{ fontSize: '18px', fontWeight: 600, color: 'var(--accent-brass)' }}>
                    {formatMoney(c.proposal.claimed_total)}
                  </div>
                </div>

                <div
                  style={{ display: 'flex', flexWrap: 'wrap', gap: '7px', paddingTop: '8px', borderTop: '1px solid var(--border-subtle)' }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {c.state === 'PROPOSED' && (
                    <Button
                      size="sm"
                      variant="primary"
                      icon={<Lock size={13} />}
                      loading={busy}
                      onClick={() => void mutate(c.case_id, () => api.lockCase(c.case_id))}
                    >
                      Lock Cart
                    </Button>
                  )}
                  {canApprove && (
                    <Button
                      size="sm"
                      variant="brass"
                      icon={<CheckCircle2 size={13} />}
                      loading={busy}
                      onClick={() => setConfirmApproveId(c.case_id)}
                    >
                      Approve & Capture
                    </Button>
                  )}
                  {['CART_LOCKED', 'CHECKED', 'AWAITING_APPROVAL'].includes(c.state) && (
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={<PauseCircle size={13} />}
                      loading={busy}
                      onClick={() => void mutate(c.case_id, () => api.holdCase(c.case_id, 900))}
                    >
                      Hold 15m
                    </Button>
                  )}
                  {c.state === 'HELD' && (
                    <Button
                      size="sm"
                      variant="primary"
                      icon={<PlayCircle size={13} />}
                      loading={busy}
                      onClick={() => void mutate(c.case_id, () => api.resumeCase(c.case_id))}
                    >
                      Resume
                    </Button>
                  )}
                  {!isTerminal && (
                    <>
                      <Button
                        size="sm"
                        variant="secondary"
                        icon={<RefreshCw size={13} />}
                        loading={busy}
                        onClick={() => void mutate(c.case_id, () => api.recheckCase(c.case_id))}
                      >
                        Recheck C7
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        icon={<XCircle size={13} />}
                        loading={busy}
                        onClick={() => void mutate(c.case_id, () => api.cancelCase(c.case_id))}
                      >
                        Cancel
                      </Button>
                    </>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<FileCheck2 size={13} />}
                    onClick={() => setTarget({ kind: 'case', caseData: c })}
                  >
                    Inspect /why & Receipt
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <ConfirmModal
        open={Boolean(confirmApproveId)}
        title="Approve & Capture PayPal Payment?"
        description={`Approving ${confirmApproveId} authorizes PayPal Orders v2 and executes C5 final catalog & payee verification before capturing funds.`}
        confirmLabel="Approve & Pay"
        tone="brass"
        loading={Boolean(confirmApproveId && busyCaseId === confirmApproveId)}
        onCancel={() => setConfirmApproveId(null)}
        onConfirm={() => {
          const cid = confirmApproveId;
          setConfirmApproveId(null);
          if (cid) void mutate(cid, () => api.approveCase(cid));
        }}
      />
    </div>
  );
};
