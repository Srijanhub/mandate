import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, ArrowRight, CheckCircle2, KeyRound, ShieldCheck, Smartphone } from 'lucide-react';
import { api, MandateApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { PhotonKnot } from '../components/three/PhotonKnot';
import { BrandMark, ThemeSwitcher } from '../components/ui/BrandMark';
import { Button, ErrorBanner, InfoBanner, StatusPill } from '../components/ui/Primitives';

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: {
          initialize: (cfg: {
            client_id: string;
            callback: (resp: { credential?: string }) => void;
          }) => void;
          renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void;
        };
      };
    };
  }
}

export const AuthPage: React.FC = () => {
  const { config, refreshConfig, applySession, user, isAuthenticated, sessionExpiredNotice, clearExpiredNotice } =
    useAuth();
  const navigate = useNavigate();

  const [tab, setTab] = useState<'google' | 'phone'>('google');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Google Demo state
  const [demoEmail, setDemoEmail] = useState('');
  const [demoName, setDemoName] = useState('');
  const gsiContainerRef = useRef<HTMLDivElement | null>(null);

  // Mobile OTP state
  const [phone, setPhone] = useState('');
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [otpCode, setOtpCode] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [sandboxOtp, setSandboxOtp] = useState<string | null>(null);

  useEffect(() => {
    if (!config) {
      void refreshConfig();
    }
  }, [config, refreshConfig]);

  // Mount official Google Identity Services button when live GOOGLE_CLIENT_ID is configured
  useEffect(() => {
    if (tab !== 'google' || config?.google_mode !== 'live' || !config.google_client_id) return;
    const clientId = config.google_client_id;
    let cancelled = false;

    const mountButton = () => {
      if (cancelled || !gsiContainerRef.current || !window.google?.accounts?.id) return;
      gsiContainerRef.current.innerHTML = '';
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: async (resp) => {
          if (!resp.credential) {
            setError('Google did not return an ID token.');
            return;
          }
          setBusy(true);
          setError(null);
          try {
            const session = await api.signInGoogle({ id_token: resp.credential });
            applySession(session);
            navigate('/app/command-centre');
          } catch (err) {
            setError(err instanceof MandateApiError ? err.message : 'Google verification failed');
          } finally {
            setBusy(false);
          }
        },
      });
      window.google.accounts.id.renderButton(gsiContainerRef.current, {
        theme: 'outline',
        size: 'large',
        width: 340,
      });
    };

    if (window.google?.accounts?.id) {
      mountButton();
      return () => {
        cancelled = true;
      };
    }

    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.onload = mountButton;
    document.head.appendChild(script);
    return () => {
      cancelled = true;
    };
  }, [tab, config?.google_mode, config?.google_client_id, applySession, navigate]);

  const handleGoogleDemoSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const session = await api.signInGoogle({
        demo_email: demoEmail.trim(),
        demo_name: demoName.trim() || undefined,
      });
      applySession(session);
      setSuccessMsg('Signed in with Google.');
      navigate('/app/command-centre');
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Google sign-in failed');
    } finally {
      setBusy(false);
    }
  };

  const handleRequestOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    setSandboxOtp(null);
    try {
      const res = await api.requestPhoneOtp(phone.trim());
      setChallengeId(res.challenge_id);
      if (res.demo_otp) setSandboxOtp(res.demo_otp);
      setSuccessMsg(`Verification code sent (${res.mode} mode) to ${res.phone_number}.`);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Could not send OTP');
    } finally {
      setBusy(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!challengeId) return;
    setBusy(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const session = await api.verifyPhoneOtp({
        challenge_id: challengeId,
        phone_number: phone.trim(),
        code: otpCode.trim(),
        display_name: displayName.trim() || undefined,
      });
      applySession(session);
      navigate('/app/command-centre');
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Invalid or expired OTP');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-main)' }}>
      {/* Top Bar */}
      <header
        style={{
          height: '60px',
          padding: '0 24px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <Link to="/" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--text-secondary)' }}>
            <ArrowLeft size={14} />
            Back
          </Link>
          <BrandMark />
        </div>
        <ThemeSwitcher compact />
      </header>

      {/* Split Composition */}
      <div
        style={{
          flex: 1,
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
          alignItems: 'center',
          maxWidth: '1200px',
          width: '100%',
          margin: '0 auto',
          padding: '32px 24px',
          gap: '40px',
        }}
      >
        {/* Left: Form */}
        <div
          className="glass-panel"
          style={{
            padding: '28px',
            borderRadius: 'var(--radius-lg)',
            display: 'flex',
            flexDirection: 'column',
            gap: '18px',
            maxWidth: '460px',
            width: '100%',
            justifySelf: 'center',
            boxShadow: 'var(--shadow-md)',
          }}
        >
          <div>
            <div className="mono" style={{ fontSize: '11px', color: 'var(--accent-brass)', letterSpacing: '0.09em', textTransform: 'uppercase' }}>
              Cryptographic Session Access
            </div>
            <h1 style={{ fontSize: '24px', fontWeight: 600, marginTop: '4px' }}>
              {isAuthenticated ? 'Link Another Sign-In Method' : 'Authenticate to Mandate'}
            </h1>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '6px' }}>
              {isAuthenticated
                ? `Signed in as ${user?.display_name}. Verify Google or Mobile OTP to link it to your profile.`
                : 'Sign in with Google or Mobile Number OTP to isolate your mandates, approvals, and ledger proofs.'}
            </p>
          </div>

          {sessionExpiredNotice && (
            <InfoBanner tone="warn">
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                <span>Your previous session expired. Sign in again to continue.</span>
                <button
                  type="button"
                  onClick={clearExpiredNotice}
                  style={{ background: 'transparent', border: 'none', textDecoration: 'underline', cursor: 'pointer', fontSize: '12px' }}
                >
                  Dismiss
                </button>
              </div>
            </InfoBanner>
          )}

          {isAuthenticated && (
            <div
              className="surface-elevated"
              style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}
            >
              <span style={{ fontSize: '12.5px' }}>
                Active session: <strong>{user?.email || user?.phone_number || user?.user_id}</strong>
              </span>
              <Button size="sm" variant="brass" icon={<ArrowRight size={13} />} onClick={() => navigate('/app/command-centre')}>
                Open Console
              </Button>
            </div>
          )}

          {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
          {successMsg && (
            <InfoBanner tone="verified">
              <span>{successMsg}</span>
            </InfoBanner>
          )}

          {/* Method Selector */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '6px',
              padding: '4px',
              background: 'var(--bg-subtle)',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <button
              type="button"
              onClick={() => {
                setTab('google');
                setError(null);
              }}
              style={{
                padding: '8px 10px',
                borderRadius: 'var(--radius-xs)',
                border: 'none',
                cursor: 'pointer',
                fontSize: '13px',
                fontWeight: 600,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                background: tab === 'google' ? 'var(--bg-elevated)' : 'transparent',
                color: tab === 'google' ? 'var(--text-primary)' : 'var(--text-secondary)',
              }}
            >
              <KeyRound size={14} />
              Google Sign-In
            </button>
            <button
              type="button"
              onClick={() => {
                setTab('phone');
                setError(null);
              }}
              style={{
                padding: '8px 10px',
                borderRadius: 'var(--radius-xs)',
                border: 'none',
                cursor: 'pointer',
                fontSize: '13px',
                fontWeight: 600,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                background: tab === 'phone' ? 'var(--bg-elevated)' : 'transparent',
                color: tab === 'phone' ? 'var(--text-primary)' : 'var(--text-secondary)',
              }}
            >
              <Smartphone size={14} />
              Mobile OTP
            </button>
          </div>

          {tab === 'google' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Provider mode</span>
                <StatusPill tone={config?.google_mode === 'live' ? 'verified' : config?.google_mode === 'disabled' ? 'danger' : 'warn'}>
                  {config?.google_mode || 'checking'}
                </StatusPill>
              </div>

              {config?.google_mode === 'live' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div ref={gsiContainerRef} style={{ minHeight: '42px' }} />
                  <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Verifies your OAuth ID token against backend client ID <span className="mono">{config.google_client_id?.slice(0, 18)}…</span>
                  </p>
                </div>
              )}

              {config?.google_mode === 'demo' && (
                <form onSubmit={handleGoogleDemoSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '11px' }}>
                  <InfoBanner>
                    <strong>Sandbox Google Mode</strong> (`GOOGLE_CLIENT_ID` is not set in `.env`). Add a Google OAuth Client ID to `.env` for live Google Sign-In, or sign in below for local testing:
                  </InfoBanner>
                  <Button
                    type="button"
                    variant="secondary"
                    loading={busy}
                    onClick={async () => {
                      setBusy(true);
                      setError(null);
                      try {
                        const session = await api.signInGoogle({
                          demo_email: demoEmail.trim() || 'vinay@mandate.dev',
                          demo_name: demoName.trim() || 'Vinay Khandia',
                        });
                        applySession(session);
                        navigate('/app/command-centre');
                      } catch (err) {
                        setError(err instanceof MandateApiError ? err.message : 'Demo sign-in failed');
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Quick 1-Click Demo Google Sign-In
                  </Button>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '12.5px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Or enter any Google Email</span>
                    <input
                      type="email"
                      required
                      value={demoEmail}
                      onChange={(e) => setDemoEmail(e.target.value)}
                      placeholder="you@domain.com"
                      style={{
                        padding: '9px 11px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        background: 'var(--bg-main)',
                      }}
                    />
                  </label>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '12.5px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Display Name (optional)</span>
                    <input
                      type="text"
                      value={demoName}
                      onChange={(e) => setDemoName(e.target.value)}
                      placeholder="Vinay Khandia"
                      style={{
                        padding: '9px 11px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        background: 'var(--bg-main)',
                      }}
                    />
                  </label>
                  <Button type="submit" variant="brass" size="lg" loading={busy}>
                    Continue with Google
                  </Button>
                </form>
              )}

              {config?.google_mode === 'disabled' && (
                <ErrorBanner message="Google Sign-In is disabled on this server until GOOGLE_CLIENT_ID is configured." />
              )}
            </div>
          )}

          {tab === 'phone' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>SMS Gateway</span>
                <StatusPill tone={config?.phone_mode === 'twilio' ? 'verified' : 'warn'}>
                  {config?.phone_mode || 'demo'}
                </StatusPill>
              </div>

              {!challengeId ? (
                <form onSubmit={handleRequestOtp} style={{ display: 'flex', flexDirection: 'column', gap: '11px' }}>
                  {config?.phone_mode !== 'twilio' && (
                    <InfoBanner>
                      <strong>Sandbox SMS Mode</strong> (`TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` are not set in `.env`). Real carrier SMS requires Twilio keys; in sandbox mode your 6-digit OTP appears directly on screen.
                    </InfoBanner>
                  )}
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '12.5px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Mobile Number (E.164 format)</span>
                    <input
                      type="tel"
                      required
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      placeholder="+919876543210 or +14155551234"
                      className="mono"
                      style={{
                        padding: '9px 11px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        background: 'var(--bg-main)',
                      }}
                    />
                  </label>
                  <Button type="submit" variant="brass" size="lg" loading={busy}>
                    Send 6-Digit Verification Code
                  </Button>
                </form>
              ) : (
                <form onSubmit={handleVerifyOtp} style={{ display: 'flex', flexDirection: 'column', gap: '11px' }}>
                  {sandboxOtp && (
                    <InfoBanner tone="warn">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                        <span>
                          Sandbox OTP: <strong className="mono">{sandboxOtp}</strong>
                        </span>
                        <button
                          type="button"
                          onClick={() => setOtpCode(sandboxOtp)}
                          style={{
                            background: 'transparent',
                            border: '1px solid currentColor',
                            borderRadius: 'var(--radius-xs)',
                            padding: '2px 7px',
                            fontSize: '11px',
                            cursor: 'pointer',
                          }}
                        >
                          Autofill
                        </button>
                      </div>
                    </InfoBanner>
                  )}

                  <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '12.5px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>6-Digit Code for {phone}</span>
                    <input
                      type="text"
                      required
                      maxLength={12}
                      value={otpCode}
                      onChange={(e) => setOtpCode(e.target.value)}
                      placeholder="123456"
                      className="mono"
                      style={{
                        padding: '10px 12px',
                        fontSize: '16px',
                        letterSpacing: '0.2em',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        background: 'var(--bg-main)',
                      }}
                    />
                  </label>

                  <label style={{ display: 'flex', flexDirection: 'column', gap: '5px', fontSize: '12.5px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Display Name (optional)</span>
                    <input
                      type="text"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      placeholder="Your name"
                      style={{
                        padding: '9px 11px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        background: 'var(--bg-main)',
                      }}
                    />
                  </label>

                  <div style={{ display: 'flex', gap: '8px' }}>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => {
                        setChallengeId(null);
                        setOtpCode('');
                        setSandboxOtp(null);
                      }}
                    >
                      Change Number
                    </Button>
                    <Button type="submit" variant="brass" size="lg" loading={busy} icon={<CheckCircle2 size={15} />} style={{ flex: 1 }}>
                      Verify & Sign In
                    </Button>
                  </div>
                </form>
              )}
            </div>
          )}

          <div
            style={{
              paddingTop: '12px',
              borderTop: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '12px',
              color: 'var(--text-muted)',
            }}
          >
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <ShieldCheck size={13} style={{ color: 'var(--accent-brass)' }} />
              HS256 Session JWT + Per-User Isolation
            </span>
            {config && !config.require_auth && (
              <Link to="/app/command-centre" style={{ textDecoration: 'underline', color: 'var(--text-secondary)' }}>
                Enter Dev Workspace
              </Link>
            )}
          </div>
        </div>

        {/* Right: Signature 3D Photon Knot */}
        <div
          style={{
            height: '440px',
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--border-subtle)',
            background: 'var(--bg-surface)',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          <PhotonKnot variant="auth" />
          <div
            className="glass-panel"
            style={{
              position: 'absolute',
              bottom: '16px',
              left: '16px',
              right: '16px',
              padding: '12px 14px',
              borderRadius: 'var(--radius-md)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              fontSize: '12px',
            }}
          >
            <span>Optical Knot · Identity & Cryptographic Verification</span>
            <span className="mono" style={{ color: 'var(--accent-brass)' }}>C1–C8</span>
          </div>
        </div>
      </div>
    </div>
  );
};
