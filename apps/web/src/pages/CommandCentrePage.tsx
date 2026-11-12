import React, { useEffect, useRef, useState } from 'react';
import { Send, Terminal } from 'lucide-react';
import { api, MandateApiError } from '../api/client';
import type {
  Case,
  CommandResponse,
  IntentReceipt,
  LedgerEntry,
  Mandate,
  RankedOptionResponse,
  WhyResponse,
} from '../api/types';
import {
  CaseProposalCard,
  IntentReceiptCard,
  LedgerSliceCard,
  MandateDraftCard,
  SecurityEventCard,
  ShoppingOptionsCard,
} from '../components/command/StructuredCards';
import { Button, ConfirmModal, ErrorBanner, SectionHeader } from '../components/ui/Primitives';
import { useInspector } from '../context/InspectorContext';

interface FeedItem {
  id: string;
  role: 'user' | 'system';
  text?: string;
  response?: CommandResponse;
  error?: string;
}

const QUICK_COMMANDS = [
  { label: 'Gift under 500rs', cmd: 'Buy me a gift under 500rs for my girlfriend' },
  { label: 'Gift under $60', cmd: 'Buy birthday gift under $60, verified sellers only' },
  { label: '/confirm', cmd: '/confirm' },
  { label: '/options', cmd: '/options' },
  { label: '/pick 1', cmd: '/pick 1' },
  { label: '/approve', cmd: '/approve' },
  { label: '/why', cmd: '/why' },
  { label: '/receipt', cmd: '/receipt' },
  { label: '/ledger 8', cmd: '/ledger 8' },
  { label: '/help', cmd: '/help' },
];

export const CommandCentrePage: React.FC = () => {
  const { setTarget, pushActivity } = useInspector();
  const [input, setInput] = useState('');
  const [activeMandateId, setActiveMandateId] = useState<string | null>(null);
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [pendingApproveCaseId, setPendingApproveCaseId] = useState<string | null>(null);

  const [feed, setFeed] = useState<FeedItem[]>([
    {
      id: 'welcome',
      role: 'system',
      text: 'Control plane ready. Describe a spending rule in natural language (creates a DRAFT mandate) or execute any deterministic `/` command directly.',
    },
  ]);

  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [feed]);

  useEffect(() => {
    let active = true;
    Promise.allSettled([api.listMandates(5), api.listCases({ limit: 5 })]).then(([mRes, cRes]) => {
      if (!active) return;
      if (mRes.status === 'fulfilled' && mRes.value.mandates.length > 0) {
        const latest = mRes.value.mandates[0];
        setActiveMandateId(latest.mandate_id);
        setTarget({ kind: 'mandate', mandate: latest });
      }
      if (cRes.status === 'fulfilled' && cRes.value.cases.length > 0) {
        setActiveCaseId(cRes.value.cases[0].case_id);
      }
    });
    return () => {
      active = false;
    };
  }, [setTarget]);

  const runCommand = async (rawText: string, overrides?: { mandateId?: string; caseId?: string }) => {
    const trimmed = rawText.trim();
    if (!trimmed) return;

    const userMsg: FeedItem = { id: `u-${Date.now()}`, role: 'user', text: trimmed };
    setFeed((prev) => [...prev, userMsg]);
    setInput('');
    setSubmitting(true);
    setGlobalError(null);

    try {
      const res = await api.sendCommand({
        text: trimmed,
        source: 'user_command',
        mandate_id: overrides?.mandateId ?? activeMandateId,
        case_id: overrides?.caseId ?? activeCaseId,
      });

      if (res.mandate) {
        setActiveMandateId(res.mandate.mandate_id);
        setTarget({ kind: 'mandate', mandate: res.mandate });
        pushActivity({
          label: res.command ? `/${res.command}` : 'Mandate Draft',
          detail: `${res.mandate.mandate_id} (${res.mandate.status})`,
          target: { kind: 'mandate', mandate: res.mandate },
        });
      } else if (res.case) {
        setActiveCaseId(res.case.case_id);
        setTarget({ kind: 'case', caseData: res.case });
        pushActivity({
          label: `/${res.command || 'case'}`,
          detail: `${res.case.case_id} → ${res.case.state}`,
          target: { kind: 'case', caseData: res.case },
        });
      } else if (res.options && res.options.length > 0) {
        setTarget({ kind: 'option', option: res.options[0], mandateId: res.mandate_id });
        pushActivity({
          label: '/options',
          detail: `${res.options.length} candidate options`,
          target: { kind: 'option', option: res.options[0], mandateId: res.mandate_id },
        });
      } else if (res.entries && res.entries.length > 0) {
        setTarget({ kind: 'ledger', entry: res.entries[0] });
        pushActivity({
          label: '/ledger',
          detail: `Loaded ${res.entries.length} entries`,
          target: { kind: 'ledger', entry: res.entries[0] },
        });
      }

      setFeed((prev) => [...prev, { id: `s-${Date.now()}`, role: 'system', response: res }]);
      return res;
    } catch (err) {
      const msg = err instanceof MandateApiError ? err.message : 'Command execution failed';
      setFeed((prev) => [...prev, { id: `e-${Date.now()}`, role: 'system', error: msg }]);
      return null;
    } finally {
      setSubmitting(false);
    }
  };

  const confirmAndRecommend = async (mandateId: string) => {
    setActiveMandateId(mandateId);
    const confirmed = await runCommand('/confirm', { mandateId });
    if (confirmed?.mandate?.status === 'ACTIVE') {
      await runCommand('/options', { mandateId: confirmed.mandate.mandate_id });
    }
  };

  const approveAndShowReceipt = async (caseId: string) => {
    setActiveCaseId(caseId);
    const approved = await runCommand(`/approve ${caseId}`, { caseId });
    if (approved?.case) {
      await runCommand(`/receipt ${approved.case.case_id}`, { caseId: approved.case.case_id });
    }
  };

  const handleCaseAction = (
    action: 'lock' | 'approve' | 'hold' | 'resume' | 'cancel' | 'recheck' | 'why' | 'receipt',
    caseId: string,
  ) => {
    if (action === 'approve') {
      setPendingApproveCaseId(caseId);
      return;
    }
    if (action === 'lock') {
      setSubmitting(true);
      api
        .lockCase(caseId)
        .then((res) => {
          setTarget({ kind: 'case', caseData: res.case });
          setFeed((prev) => [
            ...prev,
            {
              id: `lock-${Date.now()}`,
              role: 'system',
              response: { is_command: true, command: 'lock', case: res.case },
            },
          ]);
        })
        .catch((err) => {
          setGlobalError(err instanceof MandateApiError ? err.message : 'Failed to lock case');
        })
        .finally(() => setSubmitting(false));
      return;
    }
    const cmdMap: Record<'hold' | 'resume' | 'cancel' | 'recheck' | 'why' | 'receipt', string> = {
      hold: `/hold 15m ${caseId}`,
      resume: `/resume ${caseId}`,
      cancel: `/cancel ${caseId}`,
      recheck: `/recheck ${caseId}`,
      why: `/why ${caseId}`,
      receipt: `/receipt ${caseId}`,
    };
    void runCommand(cmdMap[action]);
  };

  const renderStructuredResponse = (res: CommandResponse) => {
    if (res.mandate) {
      return (
        <MandateDraftCard
          mandate={res.mandate as Mandate}
          needsConfirm={res.needs_confirm}
          busy={submitting}
          onConfirm={(id) => {
            setActiveMandateId(id);
            void runCommand('/confirm', { mandateId: id });
          }}
          onConfirmAndShop={(id) => void confirmAndRecommend(id)}
          onFindOptions={(id) => {
            setActiveMandateId(id);
            void runCommand('/options', { mandateId: id });
          }}
        />
      );
    }
    if (res.options) {
      return (
        <ShoppingOptionsCard
          options={res.options as RankedOptionResponse[]}
          mandateId={res.mandate_id}
          busy={submitting}
          onPick={(idx) => void runCommand(`/pick ${idx}`)}
        />
      );
    }
    if (res.case) {
      return <CaseProposalCard caseData={res.case as Case} busy={submitting} onAction={handleCaseAction} />;
    }
    if (res.receipt) {
      return <IntentReceiptCard receipt={res.receipt as IntentReceipt} />;
    }
    if (res.plain_english_reasons) {
      return <SecurityEventCard why={res as unknown as WhyResponse} />;
    }
    if (res.entries) {
      return <LedgerSliceCard entries={res.entries as LedgerEntry[]} totalCount={res.total_count} />;
    }
    if (res.commands) {
      return (
        <div className="surface-card" style={{ padding: '14px 16px' }}>
          <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px' }}>
            Supported Control-Plane Commands
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '6px' }}>
            {res.commands.map((c) => (
              <button
                key={c.name}
                type="button"
                onClick={() => setInput(`${c.name} `)}
                style={{
                  textAlign: 'left',
                  padding: '7px 9px',
                  borderRadius: 'var(--radius-xs)',
                  border: '1px solid var(--border-subtle)',
                  background: 'var(--bg-subtle)',
                  cursor: 'pointer',
                  fontSize: '12px',
                }}
              >
                <div className="mono" style={{ color: 'var(--accent-brass)', fontWeight: 600 }}>{c.name}</div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '11.5px' }}>{c.description}</div>
              </button>
            ))}
          </div>
        </div>
      );
    }
    if (res.revoked_mandates) {
      return (
        <SecurityEventCard
          tone="danger"
          title="Kill Switch Executed (/revoke)"
          lines={[
            `Revoked mandates: ${res.revoked_mandates.length}`,
            `Cancelled open cases: ${res.cancelled_cases?.length ?? 0}`,
            `Voided authorizations: ${res.voided_authorizations?.length ?? 0}`,
          ]}
        />
      );
    }
    return (
      <div className="surface-card" style={{ padding: '12px 14px', fontSize: '13px', color: 'var(--text-secondary)' }}>
        {res.message || JSON.stringify(res)}
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 104px)', minHeight: '520px' }}>
      <SectionHeader
        eyebrow="Unified Control Plane"
        title="Command Centre"
        subtitle="Natural-language intents draft unconfirmed mandates; slash commands execute deterministic state transitions."
        right={
          <div className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
            Mandate: {activeMandateId || 'None'} · Case: {activeCaseId || 'None'}
          </div>
        }
      />

      {globalError && (
        <div style={{ marginBottom: '12px' }}>
          <ErrorBanner message={globalError} onDismiss={() => setGlobalError(null)} />
        </div>
      )}

      {/* Feed */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px', paddingRight: '4px' }}>
        {feed.map((item) => (
          <div
            key={item.id}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: item.role === 'user' ? 'flex-end' : 'stretch',
            }}
          >
            {item.role === 'user' ? (
              <div
                className="mono"
                style={{
                  maxWidth: '82%',
                  padding: '9px 13px',
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-elevated)',
                  border: '1px solid var(--border-strong)',
                  fontSize: '13px',
                  color: 'var(--text-primary)',
                }}
              >
                {item.text}
              </div>
            ) : item.error ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <ErrorBanner message={item.error} />
                {activeMandateId && (
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    <Button size="sm" variant="secondary" onClick={() => void runCommand('/options')}>
                      Show Recommendations (/options)
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setInput('Buy me a gift under 500rs for my girlfriend')}>
                      Try "Buy me a gift under 500rs"
                    </Button>
                  </div>
                )}
              </div>
            ) : item.response ? (
              renderStructuredResponse(item.response)
            ) : (
              <div
                className="surface-card"
                style={{ padding: '12px 15px', fontSize: '13px', color: 'var(--text-secondary)' }}
              >
                {item.text}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <div
        className="glass-panel"
        style={{
          marginTop: '14px',
          padding: '12px',
          borderRadius: 'var(--radius-md)',
          display: 'flex',
          flexDirection: 'column',
          gap: '9px',
        }}
      >
        <div style={{ display: 'flex', gap: '6px', overflowX: 'auto', paddingBottom: '2px' }}>
          {QUICK_COMMANDS.map((q) => (
            <button
              key={q.label}
              type="button"
              className="mono"
              onClick={() => setInput(q.cmd)}
              style={{
                padding: '4px 9px',
                fontSize: '11.5px',
                borderRadius: 'var(--radius-xs)',
                border: '1px solid var(--border-subtle)',
                background: 'var(--bg-elevated)',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              {q.label}
            </button>
          ))}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void runCommand(input);
          }}
          style={{ display: 'flex', gap: '8px', alignItems: 'center' }}
        >
          <div style={{ position: 'relative', flex: 1 }}>
            <Terminal
              size={14}
              style={{
                position: 'absolute',
                left: '12px',
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--accent-brass)',
              }}
            />
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder='Enter "/options", "/approve", or describe a spending rule...'
              disabled={submitting}
              style={{
                width: '100%',
                padding: '10px 12px 10px 34px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                background: 'var(--bg-main)',
                fontSize: '13.5px',
                outline: 'none',
              }}
            />
          </div>
          <Button type="submit" variant="brass" loading={submitting} icon={<Send size={14} />}>
            Execute
          </Button>
        </form>
      </div>

      <ConfirmModal
        open={Boolean(pendingApproveCaseId)}
        title="Approve & Capture Payment?"
        description={`Confirming ${pendingApproveCaseId} triggers PayPal Orders v2 authorization + C5 final catalog & payee verification before capturing funds.`}
        confirmLabel="Approve & Pay"
        tone="brass"
        loading={submitting}
        onCancel={() => setPendingApproveCaseId(null)}
        onConfirm={() => {
          const cid = pendingApproveCaseId;
          setPendingApproveCaseId(null);
          if (cid) void approveAndShowReceipt(cid);
        }}
      />
    </div>
  );
};
