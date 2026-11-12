import React, { useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Activity,
  FileCheck2,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  Menu,
  PanelRightOpen,
  Scale,
  Settings,
  ShieldAlert,
  ShieldCheck,
  ShoppingBag,
  Terminal,
  X,
} from 'lucide-react';
import { api, MandateApiError } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { useInspector } from '../../context/InspectorContext';
import { BrandMark, ThemeSwitcher } from '../ui/BrandMark';
import { Button, ConfirmModal, ErrorBanner } from '../ui/Primitives';
import { ContextualInspector } from './ContextualInspector';

const NAV_ITEMS = [
  { to: '/app/overview', label: 'Overview', icon: LayoutDashboard },
  { to: '/app/command-centre', label: 'Command Centre', icon: Terminal },
  { to: '/app/mandates', label: 'My Mandates', icon: Scale },
  { to: '/app/shopping', label: 'Shopping & Proposals', icon: ShoppingBag },
  { to: '/app/cases', label: 'Cases & Transactions', icon: Activity },
  { to: '/app/ledger', label: 'Security Ledger', icon: FileCheck2 },
  { to: '/app/trust', label: 'Trust & Verification', icon: ShieldCheck },
  { to: '/app/demo-lab', label: 'Red-Team Demo Lab', icon: FlaskConical },
  { to: '/app/settings', label: 'Settings & Integrations', icon: Settings },
];

export const AppShell: React.FC = () => {
  const { user, logout, isAuthenticated } = useAuth();
  const { recentActivity, setTarget, mobileInspectorOpen, setMobileInspectorOpen } = useInspector();
  const location = useLocation();
  const navigate = useNavigate();

  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [shellError, setShellError] = useState<string | null>(null);

  const activeNav = NAV_ITEMS.find((item) => location.pathname.startsWith(item.to));

  const handleKillSwitch = async () => {
    setRevoking(true);
    setShellError(null);
    try {
      await api.revokeAllMandates('Emergency Kill Switch triggered from App Shell');
      setRevokeOpen(false);
      navigate('/app/mandates');
    } catch (err) {
      setShellError(err instanceof MandateApiError ? err.message : 'Failed to execute kill switch');
      setRevokeOpen(false);
    } finally {
      setRevoking(false);
    }
  };

  const sidebarContent = (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '16px 14px', gap: '16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '2px 4px' }}>
        <NavLink to="/" onClick={() => setMobileNavOpen(false)}>
          <BrandMark />
        </NavLink>
        {mobileNavOpen && (
          <button
            type="button"
            onClick={() => setMobileNavOpen(false)}
            style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}
          >
            <X size={18} />
          </button>
        )}
      </div>

      <nav aria-label="Primary Navigation" style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setMobileNavOpen(false)}
              style={({ isActive }) => ({
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                padding: '8px 10px',
                borderRadius: 'var(--radius-sm)',
                fontSize: '13px',
                fontWeight: isActive ? 600 : 500,
                background: isActive ? 'var(--bg-elevated)' : 'transparent',
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                border: isActive ? '1px solid var(--border-subtle)' : '1px solid transparent',
                transition: 'background-color 140ms ease, color 140ms ease',
              })}
            >
              <Icon size={15} style={{ color: 'var(--accent-brass)', flexShrink: 0 }} />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* Recent Activity */}
      {recentActivity.length > 0 && (
        <div style={{ marginTop: '4px', paddingTop: '12px', borderTop: '1px solid var(--border-subtle)' }}>
          <div
            className="mono"
            style={{
              fontSize: '10px',
              textTransform: 'uppercase',
              letterSpacing: '0.09em',
              color: 'var(--text-muted)',
              padding: '0 6px 6px',
            }}
          >
            Recent Activity
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {recentActivity.slice(0, 4).map((act) => (
              <button
                key={act.id}
                type="button"
                onClick={() => {
                  if (act.target) setTarget(act.target);
                  setMobileNavOpen(false);
                }}
                style={{
                  textAlign: 'left',
                  background: 'transparent',
                  border: 'none',
                  padding: '5px 6px',
                  borderRadius: 'var(--radius-xs)',
                  cursor: act.target ? 'pointer' : 'default',
                  color: 'var(--text-secondary)',
                  fontSize: '12px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '6px' }}>
                  <span style={{ fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {act.label}
                  </span>
                  <span className="mono" style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                    {act.timestamp}
                  </span>
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {act.detail}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Footer: Theme & User Profile */}
      <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: '10px', paddingTop: '12px', borderTop: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Theme</span>
          <ThemeSwitcher compact />
        </div>

        <div
          className="surface-elevated"
          style={{ padding: '10px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: '12.5px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user?.display_name || 'Guest Workspace'}
            </div>
            <div className="mono" style={{ fontSize: '10.5px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user?.email || user?.phone_number || (isAuthenticated ? user?.user_id : 'Dev / Unauthenticated')}
            </div>
          </div>
          {isAuthenticated ? (
            <button
              type="button"
              title="Sign out"
              onClick={async () => {
                await logout();
                navigate('/auth');
              }}
              style={{
                background: 'transparent',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-xs)',
                padding: '6px',
                cursor: 'pointer',
                color: 'var(--text-secondary)',
              }}
            >
              <LogOut size={13} />
            </button>
          ) : (
            <Button size="sm" variant="brass" onClick={() => navigate('/auth')}>
              Sign in
            </Button>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <div className="app-shell">
      {/* Desktop Left Sidebar */}
      <aside className="app-sidebar app-sidebar-desktop">{sidebarContent}</aside>

      {/* Mobile Drawer Navigation */}
      {mobileNavOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 70,
            display: 'flex',
            background: 'rgba(10, 12, 16, 0.56)',
            backdropFilter: 'blur(4px)',
          }}
          onClick={() => setMobileNavOpen(false)}
        >
          <aside
            className="app-sidebar"
            style={{ width: '272px' }}
            onClick={(e) => e.stopPropagation()}
          >
            {sidebarContent}
          </aside>
        </div>
      )}

      {/* Centre Main Workspace */}
      <main className="app-main">
        <header
          style={{
            height: 'var(--topbar-height)',
            padding: '0 20px',
            borderBottom: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            background: 'var(--bg-main)',
            flexShrink: 0,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              type="button"
              className="mobile-only"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Open navigation"
              style={{
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-xs)',
                padding: '6px',
                cursor: 'pointer',
              }}
            >
              <Menu size={16} />
            </button>
            <span style={{ fontSize: '14px', fontWeight: 600 }}>{activeNav?.label || 'Mandate'}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Button
              size="sm"
              variant="danger"
              icon={<ShieldAlert size={13} />}
              onClick={() => setRevokeOpen(true)}
            >
              Kill Switch (/revoke)
            </Button>
            <button
              type="button"
              onClick={() => setMobileInspectorOpen(true)}
              aria-label="Open contextual panel"
              title="Contextual Intelligence"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-xs)',
                padding: '6px 9px',
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              <PanelRightOpen size={14} />
            </button>
          </div>
        </header>

        {shellError && (
          <div style={{ padding: '12px 24px 0' }}>
            <ErrorBanner message={shellError} onDismiss={() => setShellError(null)} />
          </div>
        )}

        <div className="app-main-scroll">
          <Outlet />
        </div>
      </main>

      {/* Right Contextual Intelligence Panel */}
      <aside className="app-inspector app-inspector-desktop">
        <ContextualInspector />
      </aside>

      {/* Slide-over Inspector for Tablets/Mobile */}
      {mobileInspectorOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 75,
            display: 'flex',
            justifyContent: 'flex-end',
            background: 'rgba(10, 12, 16, 0.56)',
            backdropFilter: 'blur(4px)',
          }}
          onClick={() => setMobileInspectorOpen(false)}
        >
          <aside
            className="app-inspector"
            style={{ width: 'min(360px, 92vw)' }}
            onClick={(e) => e.stopPropagation()}
          >
            <ContextualInspector onCloseMobile={() => setMobileInspectorOpen(false)} />
          </aside>
        </div>
      )}

      <ConfirmModal
        open={revokeOpen}
        title="Trigger Emergency Kill Switch?"
        description="This invokes POST /mandates/revoke: freezes your active/draft mandates, cancels open cases, voids active PayPal authorizations, and records MANDATE_REVOKED in the hash-chained ledger."
        confirmLabel="Revoke All Active Mandates"
        tone="danger"
        loading={revoking}
        onCancel={() => setRevokeOpen(false)}
        onConfirm={handleKillSwitch}
      />
    </div>
  );
};
