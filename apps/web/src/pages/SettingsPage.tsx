import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bell, Database, KeyRound, Play, RefreshCw, Server, Workflow } from 'lucide-react';
import { api, MandateApiError } from '../api/client';
import type { IntegrationsStatusResponse, ReadyResponse } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ThemeSwitcher } from '../components/ui/BrandMark';
import { Button, ErrorBanner, InfoBanner, SectionHeader, StatusPill } from '../components/ui/Primitives';

export const SettingsPage: React.FC = () => {
  const { user, isAuthenticated } = useAuth();
  const [ready, setReady] = useState<ReadyResponse | null>(null);
  const [status, setStatus] = useState<IntegrationsStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [probing, setProbing] = useState(false);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async (probe = false) => {
    if (probe) setProbing(true);
    else setLoading(true);
    setError(null);
    try {
      const [rRes, sRes] = await Promise.all([api.ready(), api.integrationsStatus(probe)]);
      setReady(rRes);
      setStatus(sRes);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Failed to load integration diagnostics');
    } finally {
      setLoading(false);
      setProbing(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus(false);
  }, [loadStatus]);

  const runPartnerAction = async (label: string, fn: () => Promise<unknown>) => {
    setError(null);
    setActionNotice(null);
    try {
      const res = await fn();
      setActionNotice(`${label}: ${JSON.stringify(res)}`);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : `${label} failed`);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <SectionHeader
        eyebrow="Platform & Identity Configuration"
        title="Settings & Integrations"
        subtitle="Inspect active partner adapters, run live concurrent health probes, and manage identity linking or theme preferences."
        right={
          <Button
            size="sm"
            variant="brass"
            icon={<Play size={13} />}
            loading={probing}
            onClick={() => void loadStatus(true)}
          >
            Run Live Probes (?probe=true)
          </Button>
        }
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
      {actionNotice && <InfoBanner tone="verified">{actionNotice}</InfoBanner>}

      {/* Account & Theme */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px' }}>
        <div className="surface-card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '7px', fontWeight: 600 }}>
              <KeyRound size={15} style={{ color: 'var(--accent-brass)' }} />
              Identity & Isolation
            </span>
            <Link to="/auth">
              <Button size="sm" variant="secondary">
                {isAuthenticated ? 'Link Account' : 'Sign In'}
              </Button>
            </Link>
          </div>
          {user ? (
            <div style={{ fontSize: '12.5px', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div>User ID: <span className="mono">{user.user_id}</span></div>
              <div>Display Name: <strong style={{ color: 'var(--text-primary)' }}>{user.display_name}</strong></div>
              <div>Email: <span className="mono">{user.email || '—'}</span></div>
              <div>Mobile: <span className="mono">{user.phone_number || '—'}</span></div>
              <div>Providers: <span className="mono">{user.auth_providers.join(', ')}</span></div>
            </div>
          ) : (
            <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)' }}>
              Not currently signed in with a session JWT. Sign in via Google or Mobile OTP to isolate your mandates and ledger rows.
            </p>
          )}
        </div>

        <div className="surface-card" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ fontWeight: 600 }}>Appearance & Theme</div>
          <p style={{ fontSize: '12.5px', color: 'var(--text-secondary)' }}>
            Switch between Smoked Titanium (dark) and Porcelain & Steel (light), or follow your operating system setting.
          </p>
          <div>
            <ThemeSwitcher />
          </div>
          {ready && (
            <div className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)', paddingTop: '6px', borderTop: '1px solid var(--border-subtle)' }}>
              Active runtime: PayPal={ready.paypal_mode} · Catalog={ready.catalog_provider} · LLM={ready.llm_provider}
            </div>
          )}
        </div>
      </div>

      {/* Partner Actions */}
      <div className="surface-card" style={{ padding: '16px', display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: '13.5px', fontWeight: 600 }}>Partner Operational Triggers</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          <Button
            size="sm"
            variant="secondary"
            icon={<Database size={13} />}
            onClick={() => void runPartnerAction('Elastic Sync', () => api.syncElastic())}
          >
            Sync Elastic
          </Button>
          <Button
            size="sm"
            variant="secondary"
            icon={<Workflow size={13} />}
            onClick={() => void runPartnerAction('Render Workflow', () => api.triggerRenderWorkflow([]))}
          >
            Trigger Render Sweep
          </Button>
          <Button
            size="sm"
            variant="secondary"
            icon={<Bell size={13} />}
            onClick={() => void runPartnerAction('Zapier Test', () => api.testZapier())}
          >
            Test Notifier
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon={<RefreshCw size={13} />}
            loading={loading}
            onClick={() => void loadStatus(false)}
          >
            Reload Status
          </Button>
        </div>
      </div>

      {/* Services Table */}
      {status && (
        <div className="surface-card" style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12.5px' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', textAlign: 'left', color: 'var(--text-muted)' }}>
                <th style={{ padding: '11px 14px' }}>Integration</th>
                <th style={{ padding: '11px 14px' }}>Configured</th>
                <th style={{ padding: '11px 14px' }}>Mode</th>
                <th style={{ padding: '11px 14px' }}>Live Probe</th>
                <th style={{ padding: '11px 14px' }}>Details</th>
              </tr>
            </thead>
            <tbody>
              {status.services.map((svc) => (
                <tr key={svc.name} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '10px 14px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '7px' }}>
                    <Server size={13} style={{ color: 'var(--accent-brass)' }} />
                    {svc.name}
                  </td>
                  <td style={{ padding: '10px 14px' }}>
                    <StatusPill tone={svc.configured ? 'verified' : 'neutral'}>
                      {svc.configured ? 'Configured' : 'Fallback'}
                    </StatusPill>
                  </td>
                  <td className="mono" style={{ padding: '10px 14px', color: 'var(--text-secondary)' }}>
                    {svc.mode}
                  </td>
                  <td style={{ padding: '10px 14px' }}>
                    {svc.live_ok === null || svc.live_ok === undefined ? (
                      <span style={{ color: 'var(--text-muted)' }}>Not probed</span>
                    ) : (
                      <StatusPill tone={svc.live_ok ? 'verified' : 'danger'}>
                        {svc.live_ok ? 'Healthy' : 'Error'}
                      </StatusPill>
                    )}
                  </td>
                  <td className="mono" style={{ padding: '10px 14px', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                    {JSON.stringify(svc.details)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
