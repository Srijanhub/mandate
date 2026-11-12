import React from 'react';
import { AlertTriangle, CheckCircle2, Info, Loader2, ShieldAlert } from 'lucide-react';
import type { StatusTone } from '../../utils/format';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'brass' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  disabled,
  children,
  style,
  ...rest
}) => {
  const padding = size === 'sm' ? '6px 11px' : size === 'lg' ? '11px 20px' : '8px 14px';
  const fontSize = size === 'sm' ? '12.5px' : size === 'lg' ? '14px' : '13px';

  const variantStyles: Record<NonNullable<ButtonProps['variant']>, React.CSSProperties> = {
    primary: {
      background: 'var(--text-primary)',
      color: 'var(--bg-main)',
      border: '1px solid transparent',
    },
    brass: {
      background: 'var(--accent-brass)',
      color: '#101216',
      border: '1px solid transparent',
    },
    secondary: {
      background: 'var(--bg-elevated)',
      color: 'var(--text-primary)',
      border: '1px solid var(--border-subtle)',
    },
    danger: {
      background: 'var(--status-danger-bg)',
      color: 'var(--status-danger-fg)',
      border: '1px solid var(--status-danger-border)',
    },
    ghost: {
      background: 'transparent',
      color: 'var(--text-secondary)',
      border: '1px solid transparent',
    },
  };

  return (
    <button
      disabled={disabled || loading}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '7px',
        padding,
        fontSize,
        fontWeight: 500,
        borderRadius: 'var(--radius-sm)',
        cursor: disabled || loading ? 'not-allowed' : 'pointer',
        opacity: disabled || loading ? 0.56 : 1,
        transition: 'opacity 150ms ease, transform 150ms ease, background-color 150ms ease',
        whiteSpace: 'nowrap',
        ...variantStyles[variant],
        ...style,
      }}
      {...rest}
    >
      {loading ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : icon}
      {children}
    </button>
  );
};

export const StatusPill: React.FC<{
  tone?: StatusTone;
  children: React.ReactNode;
  mono?: boolean;
}> = ({ tone = 'neutral', children, mono = false }) => {
  const palette: Record<StatusTone, { bg: string; fg: string; border: string }> = {
    verified: {
      bg: 'var(--status-verified-bg)',
      fg: 'var(--status-verified-fg)',
      border: 'var(--status-verified-border)',
    },
    warn: {
      bg: 'var(--status-warn-bg)',
      fg: 'var(--status-warn-fg)',
      border: 'var(--status-warn-border)',
    },
    danger: {
      bg: 'var(--status-danger-bg)',
      fg: 'var(--status-danger-fg)',
      border: 'var(--status-danger-border)',
    },
    neutral: {
      bg: 'var(--status-neutral-bg)',
      fg: 'var(--status-neutral-fg)',
      border: 'var(--status-neutral-border)',
    },
  };
  const c = palette[tone];
  return (
    <span
      className={mono ? 'mono' : undefined}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        padding: '2px 8px',
        fontSize: '11.5px',
        fontWeight: 600,
        letterSpacing: '0.02em',
        borderRadius: 'var(--radius-xs)',
        background: c.bg,
        color: c.fg,
        border: `1px solid ${c.border}`,
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  );
};

export const ErrorBanner: React.FC<{
  message: string;
  onDismiss?: () => void;
}> = ({ message, onDismiss }) => (
  <div
    role="alert"
    style={{
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: '12px',
      padding: '11px 14px',
      borderRadius: 'var(--radius-sm)',
      background: 'var(--status-danger-bg)',
      border: '1px solid var(--status-danger-border)',
      color: 'var(--status-danger-fg)',
      fontSize: '13px',
    }}
  >
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
      <ShieldAlert size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
      <span>{message}</span>
    </div>
    {onDismiss && (
      <button
        type="button"
        onClick={onDismiss}
        style={{
          background: 'transparent',
          border: 'none',
          color: 'inherit',
          cursor: 'pointer',
          fontSize: '12px',
          textDecoration: 'underline',
        }}
      >
        Dismiss
      </button>
    )}
  </div>
);

export const InfoBanner: React.FC<{
  tone?: 'warn' | 'verified' | 'neutral';
  children: React.ReactNode;
}> = ({ tone = 'neutral', children }) => {
  const Icon = tone === 'verified' ? CheckCircle2 : tone === 'warn' ? AlertTriangle : Info;
  const styles =
    tone === 'verified'
      ? {
          bg: 'var(--status-verified-bg)',
          fg: 'var(--status-verified-fg)',
          border: 'var(--status-verified-border)',
        }
      : tone === 'warn'
        ? {
            bg: 'var(--status-warn-bg)',
            fg: 'var(--status-warn-fg)',
            border: 'var(--status-warn-border)',
          }
        : {
            bg: 'var(--bg-subtle)',
            fg: 'var(--text-secondary)',
            border: 'var(--border-subtle)',
          };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '9px',
        padding: '10px 14px',
        borderRadius: 'var(--radius-sm)',
        background: styles.bg,
        border: `1px solid ${styles.border}`,
        color: styles.fg,
        fontSize: '13px',
      }}
    >
      <Icon size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
      <div style={{ flex: 1 }}>{children}</div>
    </div>
  );
};

export const EmptyState: React.FC<{
  icon?: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}> = ({ icon, title, description, action }) => (
  <div
    className="surface-card"
    style={{
      padding: '36px 24px',
      textAlign: 'center',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: '10px',
    }}
  >
    {icon && (
      <div
        style={{
          width: '42px',
          height: '42px',
          borderRadius: 'var(--radius-md)',
          background: 'var(--bg-subtle)',
          border: '1px solid var(--border-subtle)',
          display: 'grid',
          placeItems: 'center',
          color: 'var(--accent-brass)',
        }}
      >
        {icon}
      </div>
    )}
    <h3 style={{ fontSize: '15px', fontWeight: 600 }}>{title}</h3>
    <p style={{ fontSize: '13px', color: 'var(--text-secondary)', maxWidth: '420px' }}>{description}</p>
    {action && <div style={{ marginTop: '6px' }}>{action}</div>}
  </div>
);

export const SectionHeader: React.FC<{
  eyebrow?: string;
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}> = ({ eyebrow, title, subtitle, right }) => (
  <div
    style={{
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      gap: '12px',
      marginBottom: '20px',
      paddingBottom: '14px',
      borderBottom: '1px solid var(--border-subtle)',
    }}
  >
    <div>
      {eyebrow && (
        <div
          className="mono"
          style={{
            fontSize: '11px',
            letterSpacing: '0.09em',
            textTransform: 'uppercase',
            color: 'var(--accent-brass)',
            marginBottom: '4px',
          }}
        >
          {eyebrow}
        </div>
      )}
      <h1 style={{ fontSize: '21px', fontWeight: 600 }}>{title}</h1>
      {subtitle && (
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '3px' }}>{subtitle}</p>
      )}
    </div>
    {right && <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>{right}</div>}
  </div>
);

export const ConfirmModal: React.FC<{
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  tone?: 'brass' | 'danger' | 'primary';
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}> = ({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  tone = 'danger',
  loading = false,
  onConfirm,
  onCancel,
}) => {
  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 80,
        background: 'rgba(10, 12, 16, 0.62)',
        backdropFilter: 'blur(6px)',
        display: 'grid',
        placeItems: 'center',
        padding: '16px',
      }}
    >
      <div
        className="surface-elevated"
        style={{
          width: '100%',
          maxWidth: '420px',
          padding: '22px',
          boxShadow: 'var(--shadow-md)',
        }}
      >
        <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '8px' }}>{title}</h3>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '18px' }}>{description}</p>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
          <Button variant="secondary" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button variant={tone} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
};
