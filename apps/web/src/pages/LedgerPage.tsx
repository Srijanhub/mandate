import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, FileCheck2, RefreshCw, Search, ShieldAlert } from 'lucide-react';
import { api, MandateApiError } from '../api/client';
import type {
  AgentTrustScore,
  ElasticSearchHit,
  LedgerEntry,
  LedgerVerificationResult,
} from '../api/types';
import { Button, EmptyState, ErrorBanner, SectionHeader, StatusPill } from '../components/ui/Primitives';
import { useInspector } from '../context/InspectorContext';
import { formatDateTime, truncateHash } from '../utils/format';

const PAGE_SIZE = 25;

export const LedgerPage: React.FC = () => {
  const { setTarget } = useInspector();
  const [rows, setRows] = useState<LedgerEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [eventFilter, setEventFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchHits, setSearchHits] = useState<ElasticSearchHit[] | null>(null);
  const [searchMode, setSearchMode] = useState<string | null>(null);

  const [verify, setVerify] = useState<LedgerVerificationResult | null>(null);
  const [trust, setTrust] = useState<AgentTrustScore | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [lRes, vRes, tRes] = await Promise.all([
        api.listLedger({
          event_type: eventFilter.trim() || undefined,
          startRow: page * PAGE_SIZE,
          endRow: (page + 1) * PAGE_SIZE,
          sortDir,
        }),
        api.verifyLedger(),
        api.trustScore(),
      ]);
      setRows(lRes.rows);
      setTotal(lRes.total_count);
      setVerify(vRes);
      setTrust(tRes);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Failed to load security ledger');
    } finally {
      setLoading(false);
    }
  }, [page, sortDir, eventFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleElasticSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) {
      setSearchHits(null);
      setSearchMode(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.searchLedger(searchQuery.trim(), 25);
      setSearchHits(res.hits);
      setSearchMode(res.mode);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Ledger search failed');
    } finally {
      setLoading(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <SectionHeader
        eyebrow="Cryptographic Evidence Store"
        title="Security Ledger"
        subtitle="SHA-256 hash-chained audit trail across mandates, C1–C8 checkpoints, auth sign-ins, and PayPal operations."
        right={
          <Button size="sm" variant="secondary" icon={<RefreshCw size={13} />} loading={loading} onClick={load}>
            Verify & Refresh
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      {/* Verification Status & Trust Strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '12px' }}>
        <div className="surface-card" style={{ padding: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Hash-Chain Verification (`GET /ledger/verify`)</div>
            <div style={{ fontSize: '15px', fontWeight: 600, marginTop: '4px' }}>
              {verify
                ? verify.valid
                  ? `${verify.verified_entries} of ${verify.total_entries} entries verified`
                  : `Tampering detected at seq #${verify.first_broken_seq}`
                : 'Verifying…'}
            </div>
            {verify && !verify.valid && verify.broken_reason && (
              <div style={{ fontSize: '12px', color: 'var(--status-danger-fg)', marginTop: '3px' }}>
                {verify.broken_reason}
              </div>
            )}
          </div>
          {verify && (
            <StatusPill tone={verify.valid ? 'verified' : 'danger'}>
              {verify.valid ? (
                <>
                  <CheckCircle2 size={12} /> CHAIN VALID
                </>
              ) : (
                <>
                  <ShieldAlert size={12} /> TAMPERED
                </>
              )}
            </StatusPill>
          )}
        </div>

        <div className="surface-card" style={{ padding: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Agent Trust Score (`GET /ledger/trust-score`)</div>
            <div className="tabular" style={{ fontSize: '20px', fontWeight: 600, marginTop: '3px' }}>
              {trust ? `${trust.trust_score_percent.toFixed(1)}%` : '—'}
            </div>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
              {trust ? `${trust.clean_verified_cases} clean · ${trust.blocked_or_flagged_cases} blocked/flagged` : ''}
            </div>
          </div>
          <StatusPill tone="neutral" mono>
            {trust ? `${trust.total_ledger_entries} logs` : '—'}
          </StatusPill>
        </div>
      </div>

      {/* Filters & Search */}
      <div className="surface-card" style={{ padding: '14px', display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center' }}>
        <form onSubmit={handleElasticSearch} style={{ display: 'flex', flex: '1 1 280px', gap: '8px' }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search ledger events, case IDs, or actors (Elastic / fallback)..."
              style={{
                width: '100%',
                padding: '8px 10px 8px 30px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                background: 'var(--bg-main)',
              }}
            />
          </div>
          <Button type="submit" size="sm" variant="primary" loading={loading}>
            Search
          </Button>
          {searchHits && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setSearchQuery('');
                setSearchHits(null);
                setSearchMode(null);
              }}
            >
              Clear
            </Button>
          )}
        </form>

        <input
          type="text"
          value={eventFilter}
          onChange={(e) => {
            setPage(0);
            setEventFilter(e.target.value);
          }}
          placeholder="Filter exact event_type..."
          className="mono"
          style={{
            padding: '8px 10px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            background: 'var(--bg-main)',
            fontSize: '12px',
          }}
        />

        <Button
          size="sm"
          variant="secondary"
          onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
        >
          Order: {sortDir.toUpperCase()}
        </Button>
      </div>

      {/* Search Hits View */}
      {searchHits ? (
        <div className="surface-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong style={{ fontSize: '13.5px' }}>Search Results ({searchHits.length})</strong>
            {searchMode && <StatusPill tone="neutral">{searchMode}</StatusPill>}
          </div>
          {searchHits.length === 0 ? (
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No matching ledger records for your account.</p>
          ) : (
            searchHits.map((h) => (
              <div
                key={h.id}
                style={{
                  padding: '10px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-subtle)',
                  background: 'var(--bg-subtle)',
                  fontSize: '12px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span className="mono" style={{ fontWeight: 600 }}>{String(h.source.event_type || h.id)}</span>
                  <span className="mono" style={{ color: 'var(--text-muted)' }}>score {h.score.toFixed(2)}</span>
                </div>
                <div className="mono" style={{ color: 'var(--text-secondary)', marginTop: '3px' }}>
                  actor={String(h.source.actor || '—')} · case={String(h.source.case_id || '—')}
                </div>
              </div>
            ))
          )}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<FileCheck2 size={18} />}
          title="No ledger entries yet"
          description="Signed-in actions, mandates, and payment checkpoints will appear here sequentially."
        />
      ) : (
        <div className="surface-card" style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12.5px' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', textAlign: 'left', color: 'var(--text-muted)' }}>
                <th style={{ padding: '11px 14px' }}>Seq</th>
                <th style={{ padding: '11px 14px' }}>Event Type</th>
                <th style={{ padding: '11px 14px' }}>Actor</th>
                <th style={{ padding: '11px 14px' }}>Case / Mandate</th>
                <th style={{ padding: '11px 14px' }}>SHA-256 Hash</th>
                <th style={{ padding: '11px 14px' }}>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((entry) => {
                const flagged =
                  (verify && !verify.valid && verify.first_broken_seq === entry.seq) ||
                  entry.event_type.includes('TAMPER') ||
                  entry.event_type.includes('ILLEGAL') ||
                  entry.event_type.includes('BLOCK');
                return (
                  <tr
                    key={entry.id}
                    onClick={() => setTarget({ kind: 'ledger', entry })}
                    style={{
                      borderBottom: '1px solid var(--border-subtle)',
                      cursor: 'pointer',
                      background: flagged ? 'var(--status-danger-bg)' : 'transparent',
                    }}
                  >
                    <td className="mono" style={{ padding: '10px 14px', fontWeight: 600, color: 'var(--accent-brass)' }}>
                      #{entry.seq}
                    </td>
                    <td style={{ padding: '10px 14px', fontWeight: 500 }}>
                      <StatusPill tone={flagged ? 'danger' : 'neutral'} mono>
                        {entry.event_type}
                      </StatusPill>
                    </td>
                    <td className="mono" style={{ padding: '10px 14px', color: 'var(--text-secondary)' }}>
                      {entry.actor}
                    </td>
                    <td className="mono" style={{ padding: '10px 14px', color: 'var(--text-secondary)' }}>
                      {entry.case_id || entry.mandate_id || '—'}
                    </td>
                    <td className="mono" style={{ padding: '10px 14px', color: 'var(--text-muted)' }}>
                      {truncateHash(entry.hash, 10, 6)}
                    </td>
                    <td style={{ padding: '10px 14px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                      {formatDateTime(entry.created_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Page {page + 1} of {totalPages} ({total} total entries)
            </span>
            <div style={{ display: 'flex', gap: '6px' }}>
              <Button size="sm" variant="secondary" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <Button size="sm" variant="secondary" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>
                Next
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
