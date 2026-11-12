import React from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme, type ThemeMode } from '../../theme/ThemeProvider';

export const BrandMark: React.FC<{ compact?: boolean }> = ({ compact = false }) => (
  <div style={{ display: 'inline-flex', alignItems: 'center', gap: '10px' }}>
    <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <rect
        x="1.5"
        y="1.5"
        width="29"
        height="29"
        rx="7"
        stroke="var(--border-strong)"
        fill="var(--bg-elevated)"
      />
      <path
        d="M16 6.5C21 6.5 24.5 10.2 23.2 14.8C22 19.2 17.5 24.8 12.6 23C7.7 21.2 8.4 14.5 12.2 11.4C16 8.3 23.5 11.5 22.3 17.2C21 22.8 13 24 10 19.2C7.2 14.6 11 6.5 16 6.5Z"
        stroke="var(--accent-titanium)"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <circle cx="16" cy="16" r="2.6" fill="var(--accent-brass)" />
    </svg>
    {!compact && (
      <div>
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: '15px',
            fontWeight: 700,
            letterSpacing: '0.02em',
            lineHeight: 1.1,
          }}
        >
          MANDATE
        </div>
        <div
          className="mono"
          style={{
            fontSize: '10px',
            letterSpacing: '0.1em',
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
          }}
        >
          Spending Firewall
        </div>
      </div>
    )}
  </div>
);

export const ThemeSwitcher: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  const { mode, setMode } = useTheme();
  const options: Array<{ id: ThemeMode; label: string; icon: React.ReactNode }> = [
    { id: 'dark', label: 'Dark', icon: <Moon size={13} /> },
    { id: 'light', label: 'Light', icon: <Sun size={13} /> },
    { id: 'system', label: 'Auto', icon: <Monitor size={13} /> },
  ];

  return (
    <div
      role="group"
      aria-label="Theme preference"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '3px',
        borderRadius: 'var(--radius-sm)',
        background: 'var(--bg-subtle)',
        border: '1px solid var(--border-subtle)',
        gap: '2px',
      }}
    >
      {options.map((opt) => {
        const active = mode === opt.id;
        return (
          <button
            key={opt.id}
            type="button"
            title={`${opt.label} theme`}
            onClick={() => setMode(opt.id)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: compact ? '4px 7px' : '4px 9px',
              fontSize: '11.5px',
              fontWeight: active ? 600 : 500,
              borderRadius: 'var(--radius-xs)',
              border: 'none',
              cursor: 'pointer',
              background: active ? 'var(--bg-elevated)' : 'transparent',
              color: active ? 'var(--text-primary)' : 'var(--text-muted)',
              boxShadow: active ? 'var(--shadow-sm)' : 'none',
            }}
          >
            {opt.icon}
            {!compact && <span>{opt.label}</span>}
          </button>
        );
      })}
    </div>
  );
};
