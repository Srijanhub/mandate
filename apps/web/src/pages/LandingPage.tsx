import React from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  CheckCircle2,
  FileCheck2,
  FlaskConical,
  Lock,
  Scale,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { PhotonKnot } from '../components/three/PhotonKnot';
import { BrandMark, ThemeSwitcher } from '../components/ui/BrandMark';
import { Button, StatusPill } from '../components/ui/Primitives';

const WORKFLOW_STEPS = [
  { step: '01', title: 'Define a Spending Mandate', detail: 'Compile natural-language caps, seller trust policies, and expiration rules into a versioned Mandate.' },
  { step: '02', title: 'Agent Proposes a Purchase', detail: 'Your 2-tool shopping agent searches verified catalogs with zero direct PayPal credentials.' },
  { step: '03', title: 'Deterministic Rules Verify', detail: 'Mandate Core runs C1–C3 rules, HTML/CSS sanitization, and conflict checks without short-circuiting.' },
  { step: '04', title: 'Human Approves', detail: 'Approve or hold directly via UI or pre-LLM `/` slash commands before any money moves.' },
  { step: '05', title: 'PayPal Orders v2 & ProofGuard', detail: 'Checkpoint C5 verifies authoritative price and payee before capture — auto-voiding on drift or tampering.' },
  { step: '06', title: 'SHA-256 Ledger & Receipt', detail: 'Every state change, checkpoint, and Intent Receipt hash is chained immutably in PostgreSQL.' },
];

const ARCHITECTURE_PILLARS = [
  {
    icon: Scale,
    title: 'Deterministic Policy Engine',
    detail: 'Exact Decimal arithmetic (`Money` rejects floats), spend caps, velocity windows, and verified seller allowlists execute in pure Python.',
  },
  {
    icon: Terminal,
    title: 'Pre-LLM Command Boundary',
    detail: 'Control-plane `/` commands execute before any model call; hidden HTML/CSS product injections cannot trigger approvals or mutations.',
  },
  {
    icon: Lock,
    title: 'C1–C8 Checkpoints & Fail-Closed',
    detail: 'Timeouts, upstream gateway failures, or AI Auditor uncertainties escalate to `flag` or `block` — never `ok`.',
  },
  {
    icon: FileCheck2,
    title: 'Hash-Chained Audit Ledger & Receipts',
    detail: 'Every ledger row links to `prev_hash` (`SHA-256`) alongside constant-time verifiable Intent Receipts.',
  },
];

const DEMO_HIGHLIGHTS = [
  { code: 'R1', name: 'Overspend Cap', outcome: 'BLOCKED · EXCEEDS_MAX_TOTAL' },
  { code: 'R3', name: 'Payee Swap Mid-Checkout', outcome: 'C5 catches PAYEE_MISMATCH → PayPal Auth Voided' },
  { code: 'R4', name: 'Price Drift During Hold', outcome: 'C7 DriftDetector → NEEDS_RECONFIRM' },
  { code: 'R6', name: 'Control-Plane Command Injection', outcome: 'Untrusted `/approve` rejected pre-LLM' },
  { code: 'R9', name: 'Ledger Row Tampering', outcome: 'GET /ledger/verify pinpoints exact broken seq' },
  { code: 'R10', name: 'Hidden HTML / CSS Override', outcome: 'Sanitized & blocked over cap with Intent Receipt' },
  { code: 'R11', name: 'Currency Switch Attack', outcome: '30 EUR rejected against USD mandate' },
  { code: 'R13', name: 'Arithmetic Tampering', outcome: 'Claimed $1 unit / $0.50 total caught by ProofGuard' },
];

const TEAM = [
  'Vinay Khandia',
  'Harshit Neog',
  'Srijan Halder',
  'Kaif Ahmed Khan',
  'Aarman Arzare',
];

export const LandingPage: React.FC = () => {
  const { isAuthenticated } = useAuth();

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-main)', color: 'var(--text-primary)' }}>
      {/* Navigation */}
      <header
        className="glass-panel"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 50,
          borderLeft: 'none',
          borderRight: 'none',
          borderTop: 'none',
        }}
      >
        <div
          style={{
            maxWidth: '1240px',
            margin: '0 auto',
            padding: '0 24px',
            height: '64px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '16px',
          }}
        >
          <BrandMark />

          <nav style={{ display: 'flex', alignItems: 'center', gap: '24px', fontSize: '13.5px', color: 'var(--text-secondary)' }}>
            <a href="#workflow">How It Works</a>
            <a href="#architecture">Security</a>
            <a href="#demo-lab">Demo Lab</a>
          </nav>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <ThemeSwitcher compact />
            <Link to={isAuthenticated ? '/app/command-centre' : '/auth'}>
              <Button variant="brass" size="md" icon={<ArrowRight size={14} />}>
                {isAuthenticated ? 'Open Console' : 'Get Started'}
              </Button>
            </Link>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section
        style={{
          maxWidth: '1240px',
          margin: '0 auto',
          padding: '56px 24px 64px',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          alignItems: 'center',
          gap: '40px',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            <StatusPill tone="warn" mono>
              PAYPAL ORDERS V2 · AGENT SPENDING FIREWALL
            </StatusPill>
          </div>

          <h1
            style={{
              fontSize: 'clamp(2.1rem, 4.1vw, 3.35rem)',
              fontWeight: 700,
              lineHeight: 1.07,
              letterSpacing: '-0.03em',
            }}
          >
            Give AI the freedom to act. Keep control of every rupee.
          </h1>

          <p style={{ fontSize: '16px', color: 'var(--text-secondary)', maxWidth: '540px', lineHeight: 1.65 }}>
            Define the rules. Let your agents act within them. Verify every transaction with deterministic PayPal
            checkpoints and a tamper-evident SHA-256 audit ledger.
          </p>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', paddingTop: '6px' }}>
            <Link to={isAuthenticated ? '/app/command-centre' : '/auth'}>
              <Button variant="brass" size="lg" icon={<ArrowRight size={15} />}>
                Get Started
              </Button>
            </Link>
            <a href="#workflow">
              <Button variant="secondary" size="lg">
                Explore How It Works
              </Button>
            </a>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
              gap: '16px',
              marginTop: '14px',
              paddingTop: '18px',
              borderTop: '1px solid var(--border-subtle)',
            }}
          >
            <div>
              <div className="mono" style={{ fontSize: '18px', fontWeight: 600, color: 'var(--accent-brass)' }}>
                C1–C8
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Verified PayPal Gates</div>
            </div>
            <div>
              <div className="mono" style={{ fontSize: '18px', fontWeight: 600 }}>
                SHA-256
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Hash-Chained Ledger</div>
            </div>
            <div>
              <div className="mono" style={{ fontSize: '18px', fontWeight: 600 }}>
                R1–R13
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Live Red-Team Suite</div>
            </div>
          </div>
        </div>

        {/* Hero Photon Knot */}
        <div
          style={{
            height: '470px',
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--border-subtle)',
            background: 'var(--bg-surface)',
            position: 'relative',
            overflow: 'hidden',
            boxShadow: 'var(--shadow-md)',
          }}
        >
          <PhotonKnot variant="hero" />
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
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '7px' }}>
              <ShieldCheck size={14} style={{ color: 'var(--accent-brass)' }} />
              AI agents can spend your money. Mandate proves every dollar.
            </span>
            <span className="mono" style={{ color: 'var(--text-muted)' }}>Fail-Closed</span>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section
        id="workflow"
        style={{
          borderTop: '1px solid var(--border-subtle)',
          background: 'var(--bg-sidebar)',
          padding: '64px 24px',
        }}
      >
        <div style={{ maxWidth: '1240px', margin: '0 auto' }}>
          <div style={{ marginBottom: '32px' }}>
            <div className="mono" style={{ fontSize: '11px', color: 'var(--accent-brass)', letterSpacing: '0.09em', textTransform: 'uppercase' }}>
              Execution Lifecycle
            </div>
            <h2 style={{ fontSize: '28px', fontWeight: 600, marginTop: '4px' }}>
              Six deterministic steps from intent to verified settlement
            </h2>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(290px, 1fr))',
              gap: '1px',
              background: 'var(--border-subtle)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              overflow: 'hidden',
            }}
          >
            {WORKFLOW_STEPS.map((s) => (
              <div
                key={s.step}
                style={{
                  background: 'var(--bg-surface)',
                  padding: '22px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                }}
              >
                <span className="mono" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--accent-brass)' }}>
                  STEP {s.step}
                </span>
                <h3 style={{ fontSize: '15.5px', fontWeight: 600 }}>{s.title}</h3>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{s.detail}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Security Architecture */}
      <section id="architecture" style={{ maxWidth: '1240px', margin: '0 auto', padding: '64px 24px' }}>
        <div style={{ maxWidth: '680px', marginBottom: '32px' }}>
          <div className="mono" style={{ fontSize: '11px', color: 'var(--accent-brass)', letterSpacing: '0.09em', textTransform: 'uppercase' }}>
            Security Architecture
          </div>
          <h2 style={{ fontSize: '28px', fontWeight: 600, marginTop: '4px' }}>
            LLMs can assist. Deterministic rules enforce.
          </h2>
          <p style={{ fontSize: '14px', color: 'var(--text-secondary)', marginTop: '8px' }}>
            Language models interpret intent and rank catalog options, but pure Python state machines, exact Decimal rules,
            and PayPal order queries make every binding financial decision.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
          {ARCHITECTURE_PILLARS.map((p) => {
            const Icon = p.icon;
            return (
              <div key={p.title} className="surface-card" style={{ padding: '22px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div
                  style={{
                    width: '36px',
                    height: '36px',
                    borderRadius: 'var(--radius-sm)',
                    background: 'var(--accent-brass-soft)',
                    border: '1px solid var(--accent-brass-border)',
                    display: 'grid',
                    placeItems: 'center',
                    color: 'var(--accent-brass)',
                  }}
                >
                  <Icon size={17} />
                </div>
                <h3 style={{ fontSize: '15px', fontWeight: 600 }}>{p.title}</h3>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{p.detail}</p>
              </div>
            );
          })}
        </div>
      </section>

      {/* Demo Lab Showcase */}
      <section
        id="demo-lab"
        style={{
          borderTop: '1px solid var(--border-subtle)',
          background: 'var(--bg-sidebar)',
          padding: '64px 24px',
        }}
      >
        <div style={{ maxWidth: '1240px', margin: '0 auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: '16px', marginBottom: '26px' }}>
            <div>
              <div className="mono" style={{ fontSize: '11px', color: 'var(--accent-brass)', letterSpacing: '0.09em', textTransform: 'uppercase' }}>
                Adversarial Verification
              </div>
              <h2 style={{ fontSize: '28px', fontWeight: 600, marginTop: '4px' }}>
                Red-Team Demo Lab (R1–R13)
              </h2>
              <p style={{ fontSize: '13.5px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                Inspect real attack defenses executed against live backend rules, PayPal mock/sandbox gates, and ledger proofs.
              </p>
            </div>
            <Link to="/app/demo-lab">
              <Button variant="secondary" icon={<FlaskConical size={14} />}>
                Launch Demo Lab
              </Button>
            </Link>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(270px, 1fr))', gap: '10px' }}>
            {DEMO_HIGHLIGHTS.map((d) => (
              <div key={d.code} className="surface-card" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className="mono" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--accent-brass)' }}>
                    {d.code}
                  </span>
                  <CheckCircle2 size={14} style={{ color: 'var(--status-verified-fg)' }} />
                </div>
                <div style={{ fontSize: '13.5px', fontWeight: 600 }}>{d.name}</div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{d.outcome}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section style={{ maxWidth: '1240px', margin: '0 auto', padding: '64px 24px', textAlign: 'center' }}>
        <div
          className="surface-card"
          style={{
            padding: '44px 28px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '14px',
          }}
        >
          <h2 style={{ fontSize: '28px', fontWeight: 600 }}>Ready to govern autonomous spending?</h2>
          <p style={{ fontSize: '14px', color: 'var(--text-secondary)', maxWidth: '520px' }}>
            Authenticate with Google or Mobile OTP, compile a spending mandate in seconds, and inspect cryptographic receipts end-to-end.
          </p>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginTop: '6px' }}>
            <Link to={isAuthenticated ? '/app/command-centre' : '/auth'}>
              <Button variant="brass" size="lg" icon={<ArrowRight size={15} />}>
                {isAuthenticated ? 'Enter Command Centre' : 'Sign In & Start'}
              </Button>
            </Link>
            <Link to="/app/overview">
              <Button variant="secondary" size="lg">
                View Workspace
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: '1px solid var(--border-subtle)', padding: '24px', fontSize: '12.5px', color: 'var(--text-muted)' }}>
        <div
          style={{
            maxWidth: '1240px',
            margin: '0 auto',
            display: 'flex',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
          }}
        >
          <span>Mandate · Autonomous AI Agent Spending Firewall for PayPal</span>
          <span>Team: {TEAM.join(' · ')}</span>
        </div>
      </footer>
    </div>
  );
};
