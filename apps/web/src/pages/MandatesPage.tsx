import React, { useCallback, useEffect, useState } from 'react';
import { Calendar, CheckCircle2, Edit3, Plus, RefreshCw, Scale } from 'lucide-react';
import { api, MandateApiError } from '../api/client';
import type { BryntumTimelineResponse, Mandate, MandateStatus } from '../api/types';
import { Button, EmptyState, ErrorBanner, SectionHeader, StatusPill } from '../components/ui/Primitives';
import { useInspector } from '../context/InspectorContext';
import { formatDateTime, formatMoney, mandateStatusTone } from '../utils/format';

export const MandatesPage: React.FC = () => {
  const { setTarget } = useInspector();
  const [mandates, setMandates] = useState<Mandate[]>([]);
  const [schedule, setSchedule] = useState<BryntumTimelineResponse | null>(null);
  const [filterStatus, setFilterStatus] = useState<MandateStatus | 'ALL'>('ALL');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [prompt, setPrompt] = useState('');
  const [editingMandate, setEditingMandate] = useState<Mandate | null>(null);
  const [amendTotal, setAmendTotal] = useState('');
  const [amendVerifiedOnly, setAmendVerifiedOnly] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [mRes, sRes] = await Promise.all([api.listMandates(100), api.mandatesSchedule()]);
      setMandates(mRes.mandates);
      setSchedule(sRes);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Failed to load mandates');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCompile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.compileMandate(prompt.trim());
      setPrompt('');
      setTarget({ kind: 'mandate', mandate: res.mandate });
      await load();
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Failed to compile mandate');
    } finally {
      setBusy(false);
    }
  };

  const handleConfirm = async (mandateId: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.confirmMandate(mandateId);
      setTarget({ kind: 'mandate', mandate: res.mandate });
      await load();
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Failed to confirm mandate');
    } finally {
      setBusy(false);
    }
  };

  const handleAmendSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingMandate) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.amendMandate(editingMandate.mandate_id, {
        max_total_amount: amendTotal.trim() || undefined,
        require_verified_seller: amendVerifiedOnly,
        actor: 'user',
      });
      setEditingMandate(null);
      setTarget({ kind: 'mandate', mandate: res.mandate });
      await load();
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Failed to amend mandate');
    } finally {
      setBusy(false);
    }
  };

  const filtered = filterStatus === 'ALL' ? mandates : mandates.filter((m) => m.status === filterStatus);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <SectionHeader
        eyebrow="Spending Policy Registry"
        title="My Mandates"
        subtitle="Compile natural-language spending caps, confirm drafts, and version-amend active rules."
        right={
          <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} loading={loading} onClick={load}>
            Refresh
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      {/* Compile New Mandate */}
      <form
        onSubmit={handleCompile}
        className="surface-card"
        style={{ padding: '16px', display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center' }}
      >
        <input
          type="text"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder='e.g. "Buy electronics accessories under $75, verified sellers only"'
          minLength={3}
          required
          style={{
            flex: '1 1 280px',
            padding: '10px 12px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            background: 'var(--bg-main)',
            fontSize: '13.5px',
          }}
        />
        <Button type="submit" variant="brass" loading={busy} icon={<Plus size={14} />}>
          Compile Draft Mandate
        </Button>
      </form>

      {/* Filter Tabs */}
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
        {(['ALL', 'ACTIVE', 'DRAFT', 'REVOKED', 'EXPIRED'] as const).map((status) => (
          <Button
            key={status}
            size="sm"
            variant={filterStatus === status ? 'primary' : 'secondary'}
            onClick={() => setFilterStatus(status)}
          >
            {status}
          </Button>
        ))}
      </div>

      {/* Amend Inline Modal */}
      {editingMandate && (
        <form
          onSubmit={handleAmendSubmit}
          className="surface-elevated"
          style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong style={{ fontSize: '14px' }}>
              Amend {editingMandate.mandate_id} (creates new DRAFT version)
            </strong>
            <Button size="sm" variant="ghost" onClick={() => setEditingMandate(null)}>
              Close
            </Button>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'flex-end' }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px' }}>
              <span style={{ color: 'var(--text-secondary)' }}>New Max Cap ({editingMandate.max_total.currency})</span>
              <input
                type="text"
                value={amendTotal}
                onChange={(e) => setAmendTotal(e.target.value)}
                className="mono"
                style={{
                  padding: '8px 10px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-subtle)',
                  background: 'var(--bg-main)',
                }}
              />
            </label>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '13px', paddingBottom: '8px' }}>
              <input
                type="checkbox"
                checked={amendVerifiedOnly}
                onChange={(e) => setAmendVerifiedOnly(e.target.checked)}
              />
              <span>Require verified seller</span>
            </label>
            <Button type="submit" variant="brass" loading={busy}>
              Save Amendment
            </Button>
          </div>
        </form>
      )}

      {/* Mandate Cards */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={<Scale size={18} />}
          title="No mandates match this filter"
          description="Compile a spending mandate above or switch status filters."
        />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '12px' }}>
          {filtered.map((m) => (
            <div
              key={`${m.mandate_id}-v${m.version}`}
              className="surface-card"
              onClick={() => setTarget({ kind: 'mandate', mandate: m })}
              style={{
                padding: '16px',
                cursor: 'pointer',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                gap: '12px',
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <span className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                    {m.mandate_id} · v{m.version}
                  </span>
                  <StatusPill tone={mandateStatusTone(m.status)}>{m.status}</StatusPill>
                </div>
                <div style={{ fontSize: '14px', fontWeight: 500 }}>{m.intent_text}</div>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '8px',
                    marginTop: '12px',
                    padding: '10px',
                    borderRadius: 'var(--radius-sm)',
                    background: 'var(--bg-subtle)',
                    fontSize: '12px',
                  }}
                >
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Limit / Spent</div>
                    <div className="tabular" style={{ fontWeight: 600 }}>
                      <span style={{ color: 'var(--accent-brass)' }}>{formatMoney(m.max_total)}</span> /{' '}
                      {formatMoney(m.spent_total)}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Seller Trust</div>
                    <div style={{ fontWeight: 500 }}>{m.require_verified_seller ? 'Verified Only' : 'Any Seller'}</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Categories</div>
                    <div>{m.allowed_categories?.join(', ') || 'All'}</div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Expires</div>
                    <div>{formatDateTime(m.expires_at)}</div>
                  </div>
                </div>
              </div>

              <div
                style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', paddingTop: '8px', borderTop: '1px solid var(--border-subtle)' }}
                onClick={(e) => e.stopPropagation()}
              >
                {m.status === 'DRAFT' && (
                  <Button
                    size="sm"
                    variant="brass"
                    icon={<CheckCircle2 size={13} />}
                    loading={busy}
                    onClick={() => void handleConfirm(m.mandate_id)}
                  >
                    Confirm
                  </Button>
                )}
                {m.status !== 'REVOKED' && (
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<Edit3 size={13} />}
                    onClick={() => {
                      setEditingMandate(m);
                      setAmendTotal(m.max_total.amount);
                      setAmendVerifiedOnly(Boolean(m.require_verified_seller));
                    }}
                  >
                    Amend
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setTarget({ kind: 'mandate', mandate: m })}>
                  Inspect Spec
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Validity Schedule (Bryntum feed) */}
      {schedule && schedule.events.length > 0 && (
        <div className="surface-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px', fontSize: '14px', fontWeight: 600 }}>
            <Calendar size={15} style={{ color: 'var(--accent-brass)' }} />
            <span>Mandate Validity Windows (`GET /mandates/schedule`)</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {schedule.events.slice(0, 6).map((ev) => (
              <div
                key={ev.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '8px 10px',
                  borderRadius: 'var(--radius-xs)',
                  background: 'var(--bg-subtle)',
                  fontSize: '12px',
                  flexWrap: 'wrap',
                }}
              >
                <span style={{ fontWeight: 500 }}>{ev.name}</span>
                <span className="mono" style={{ color: 'var(--text-muted)' }}>
                  {formatDateTime(ev.startDate)} → {formatDateTime(ev.endDate)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
