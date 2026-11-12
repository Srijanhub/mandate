import type { CaseState, FindingSeverity, MandateStatus, Money } from '../api/types';

export function formatMoney(money?: Money | null): string {
  if (!money) return '—';
  return `${money.amount} ${money.currency}`;
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function truncateHash(hash?: string | null, start = 10, end = 6): string {
  if (!hash) return '—';
  if (hash.length <= start + end + 3) return hash;
  return `${hash.slice(0, start)}…${hash.slice(-end)}`;
}

export type StatusTone = 'verified' | 'warn' | 'danger' | 'neutral';

export function caseStateTone(state: CaseState | string): StatusTone {
  switch (state) {
    case 'VERIFIED':
    case 'CAPTURED':
    case 'APPROVED':
      return 'verified';
    case 'AWAITING_APPROVAL':
    case 'AUTHORIZED':
    case 'HELD':
    case 'NEEDS_RECONFIRM':
    case 'FLAGGED':
      return 'warn';
    case 'BLOCKED':
    case 'CANCELLED':
    case 'EXPIRED':
      return 'danger';
    default:
      return 'neutral';
  }
}

export function mandateStatusTone(status: MandateStatus | string): StatusTone {
  if (status === 'ACTIVE') return 'verified';
  if (status === 'DRAFT') return 'warn';
  if (status === 'REVOKED' || status === 'EXPIRED') return 'danger';
  return 'neutral';
}

export function findingSeverityTone(sev: FindingSeverity | string): StatusTone {
  if (sev === 'block') return 'danger';
  if (sev === 'warn') return 'warn';
  return 'verified';
}
