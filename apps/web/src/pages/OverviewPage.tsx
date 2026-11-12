import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  FileCheck2,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import { api, MandateApiError } from '../api/client';
import type {
  AgentTrustScore,
  Case,
  LedgerEntry,
  LedgerVerificationResult,
  Mandate,
} from '../api/types';
import { Button, EmptyState, ErrorBanner, SectionHeader, StatusPill } from '../components/ui/Primitives';
import { useInspector } from '../context/InspectorContext';
import { caseStateTone, formatDateTime, formatMoney, mandateStatusTone, truncateHash } from '../utils/format';

export const OverviewPage: React.FC = () => {
  const { setTarget } = useInspector();
  const [mandates, setMandates] = useState<Mandate[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [verify, setVerify] = useState<LedgerVerificationResult | null>(null);
  const [trust, setTrust] = useState<AgentTrustScore | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [mRes, cRes, lRes, vRes, tRes] = await Promise.all([
        api.listMandates(30),
        api.listCases({ limit: 30 }),
        api.listLedger({ startRow: 0, endRow: 10, sortDir: 'desc' }),
        api.verifyLedger(),
        api.trustScore(),
      ]);
      setMandates(mRes.mandates);
      setCases(cRes.cases);
      setEntries(lRes.rows);
      setVerify(vRes);
      setTrust(tRes);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Failed to load workspace overview');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const activeMandates = mandates.filter((m) => m.status === 'ACTIVE');
  const pendingApprovals = cases.filter((c) =>
    ['CHECKED', 'AWAITING_APPROVAL', 'NEEDS_RECONFIRM', 'HELD'].includes(c.state),
  );
  const flaggedOrBlocked = cases.filter((c) => ['BLOCKED', 'FLAGGED'].includes(c.state));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <SectionHeader
        eyebrow="Operational Telemetry"
        title="Overview"
        subtitle="Live workspace metrics derived exclusively from Mandate Core state and the SHA-256 audit ledger."
        right={
          <>
            <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} loading={loading} onClick={load}>
              Refresh
            </Button>
            <Link to="/app/command-centre">
              <Button size="sm" variant="brass" icon={<ArrowRight size={13} />}>
                Command Centre
              </Button>
            </Link>
          </>
        }
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      {/* KPI Strip (Strictly backend-provided) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(195px, 1fr))', gap: '12px' }}>
        <div className="surface-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: '12px' }}>
            <span>Active Mandates</span>
            <Scale size={14} style={{ color: 'var(--accent-brass)' }} />
          </div>
          <div className="tabular" style={{ fontSize: '26px', fontWeight: 600, marginTop: '6px' }}>
            {activeMandates.length}
          </div>
          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
            {mandates.length} total versioned mandates
          </div>
        </div>

        <div className="surface-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: '12px' }}>
            <span>Pending Human Action</span>
            <Activity size={14} style={{ color: 'var(--accent-brass)' }} />
          </div>
          <div className="tabular" style={{ fontSize: '26px', fontWeight: 600, marginTop: '6px' }}>
            {pendingApprovals.length}
          </div>
          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
            {flaggedOrBlocked.length} blocked or flagged
          </div>
        </div>

        <div className="surface-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: '12px' }}>
            <span>Ledger Chain Integrity</span>
            <FileCheck2 size={14} style={{ color: verify?.valid ? 'var(--status-verified-fg)' : 'var(--status-danger-fg)' }} />
          </div>
          <div style={{ marginTop: '8px' }}>
            {verify ? (
              <StatusPill tone={verify.valid ? 'verified' : 'danger'}>
                {verify.valid ? `VERIFIED (${verify.verified_entries} rows)` : `TAMPER AT SEQ #${verify.first_broken_seq}`}
              </StatusPill>
            ) : (
              '—'
            )}
          </div>
          <div className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px' }}>
            {truncateHash(verify?.latest_hash, 10, 6)}
          </div>
        </div>

        <div className="surface-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: '12px' }}>
            <span>Agent Trust Score</span>
            <ShieldCheck size={14} style={{ color: 'var(--accent-brass)' }} />
          </div>
          <div className="tabular" style={{ fontSize: '26px', fontWeight: 600, marginTop: '6px' }}>
            {trust ? `${trust.trust_score_percent.toFixed(1)}%` : '—'}
          </div>
          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
            {trust ? `${trust.clean_verified_cases}/${trust.total_cases} clean cases` : 'Waiting for telemetry'}
          </div>
        </div>
      </div>

      {/* Two-Column Activity */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '16px' }}>
        {/* Recent Cases */}
        <div className="surface-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 style={{ fontSize: '15px', fontWeight: 600 }}>Recent Cases & Approvals</h2>
            <Link to="/app/cases" style={{ fontSize: '12px', color: 'var(--accent-brass)' }}>
              View all
            </Link>
          </div>

          {cases.length === 0 ? (
            <EmptyState
              icon={<Activity size={18} />}
              title="No cases recorded yet"
              description="Compile a mandate and pick a catalog option in Command Centre to create your first verified purchase case."
            />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {cases.slice(0, 6).map((c) => (
                <button
                  key={c.case_id}
                  type="button"
                  onClick={() => setTarget({ kind: 'case', caseData: c })}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: '10px',
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-subtle)',
                    background: 'var(--bg-subtle)',
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {c.proposal.title}
                    </div>
                    <div className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {c.case_id} · {formatMoney(c.proposal.claimed_total)}
                    </div>
                  </div>
                  <StatusPill tone={caseStateTone(c.state)}>{c.state}</StatusPill>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Active Mandates & Security Events */}
        <div className="surface-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 style={{ fontSize: '15px', fontWeight: 600 }}>Recent Ledger Events</h2>
            <Link to="/app/ledger" style={{ fontSize: '12px', color: 'var(--accent-brass)' }}>
              Inspect ledger
            </Link>
          </div>

          {entries.length === 0 ? (
            <EmptyState
              icon={<ShieldCheck size={18} />}
              title="Ledger waiting for events"
              description="Every mandate draft, approval, security block, and sign-in event is cryptographically chained here."
            />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {entries.slice(0, 7).map((e) => {
                const bad = e.event_type.includes('BLOCK') || e.event_type.includes('ILLEGAL') || e.event_type.includes('REVOKE');
                return (
                  <button
                    key={e.id}
                    type="button"
                    onClick={() => setTarget({ kind: 'ledger', entry: e })}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: '10px',
                      padding: '8px 11px',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border-subtle)',
                      background: 'var(--bg-subtle)',
                      cursor: 'pointer',
                      textAlign: 'left',
                      fontSize: '12px',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                      {bad ? (
                        <ShieldAlert size={13} style={{ color: 'var(--status-danger-fg)', flexShrink: 0 }} />
                      ) : (
                        <CheckCircle2 size={13} style={{ color: 'var(--status-verified-fg)', flexShrink: 0 }} />
                      )}
                      <span className="mono" style={{ color: 'var(--accent-brass)', fontWeight: 600 }}>#{e.seq}</span>
                      <span style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {e.event_type}
                      </span>
                    </div>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      {formatDateTime(e.created_at)}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Mandates Quick Grid */}
      {mandates.length > 0 && (
        <div className="surface-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 style={{ fontSize: '15px', fontWeight: 600 }}>Mandates Snapshot</h2>
            <Link to="/app/mandates" style={{ fontSize: '12px', color: 'var(--accent-brass)' }}>
              Manage mandates
            </Link>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '10px' }}>
            {mandates.slice(0, 4).map((m) => (
              <button
                key={`${m.mandate_id}-v${m.version}`}
                type="button"
                onClick={() => setTarget({ kind: 'mandate', mandate: m })}
                style={{
                  padding: '12px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-subtle)',
                  background: 'var(--bg-subtle)',
                  textAlign: 'left',
                  cursor: 'pointer',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {m.mandate_id} · v{m.version}
                  </span>
                  <StatusPill tone={mandateStatusTone(m.status)}>{m.status}</StatusPill>
                </div>
                <div style={{ fontSize: '13px', fontWeight: 500 }}>{m.intent_text}</div>
                <div className="tabular" style={{ fontSize: '13px', fontWeight: 600, color: 'var(--accent-brass)' }}>
                  Cap: {formatMoney(m.max_total)}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
