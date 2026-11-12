import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bot, Globe, Search, ShieldCheck, ShoppingBag, Sparkles } from 'lucide-react';
import { api, MandateApiError } from '../api/client';
import type {
  KernelVerifyUrlResponse,
  Mandate,
  Product,
  RankedOptionResponse,
  ShoppingAgentResponse,
} from '../api/types';
import { Button, EmptyState, ErrorBanner, InfoBanner, SectionHeader, StatusPill } from '../components/ui/Primitives';
import { useInspector } from '../context/InspectorContext';
import { formatMoney } from '../utils/format';

export const ShoppingPage: React.FC = () => {
  const { setTarget } = useInspector();
  const navigate = useNavigate();

  const [mandates, setMandates] = useState<Mandate[]>([]);
  const [selectedMandateId, setSelectedMandateId] = useState<string>('');
  const [query, setQuery] = useState('');
  const [verifiedOnly, setVerifiedOnly] = useState(false);

  const [products, setProducts] = useState<Product[]>([]);
  const [rankedOptions, setRankedOptions] = useState<RankedOptionResponse[] | null>(null);
  const [agentRun, setAgentRun] = useState<ShoppingAgentResponse | null>(null);
  const [urlVerifications, setUrlVerifications] = useState<Record<string, KernelVerifyUrlResponse>>({});

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadInitial = useCallback(async () => {
    setLoading(true);
    try {
      const [mRes, cRes] = await Promise.all([api.listMandates(50), api.searchCatalog({ limit: 24 })]);
      const active = mRes.mandates.filter((m) => m.status === 'ACTIVE');
      setMandates(active);
      if (active.length > 0) setSelectedMandateId(active[0].mandate_id);
      setProducts(cRes.products);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Failed to load catalog');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  const handleCatalogSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setRankedOptions(null);
    try {
      const res = await api.searchCatalog({ query: query.trim(), verified_only: verifiedOnly, limit: 24 });
      setProducts(res.products);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Catalog search failed');
    } finally {
      setLoading(false);
    }
  };

  const handleAskPreference = async () => {
    if (!selectedMandateId) {
      setError('Select or confirm an ACTIVE mandate first.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.shoppingOptions(selectedMandateId, query.trim() || 'gift', 6);
      setRankedOptions(res.options);
      if (res.options.length > 0) {
        setTarget({ kind: 'option', option: res.options[0], mandateId: selectedMandateId });
      }
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Shopping options failed');
    } finally {
      setLoading(false);
    }
  };

  const handleRunAgent = async () => {
    if (!selectedMandateId) {
      setError('Select or confirm an ACTIVE mandate first.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.runShoppingAgent(selectedMandateId, query.trim() || 'gift');
      setAgentRun(res);
      if (res.case) {
        setTarget({ kind: 'case', caseData: res.case });
        setNotice(`2-tool Shopping Agent created case ${res.case.case_id} (${res.case.state}).`);
      } else {
        setNotice('Shopping Agent completed without proposing a case.');
      }
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Shopping Agent failed');
    } finally {
      setLoading(false);
    }
  };

  const handleProposePick = async (productId: string) => {
    if (!selectedMandateId) {
      setError('Create & confirm an ACTIVE mandate before proposing a purchase.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.pickShoppingProduct(selectedMandateId, productId, 1, 'Selected from Shopping Catalog');
      setTarget({ kind: 'case', caseData: res.case });
      setNotice(`Proposed & checked case ${res.case.case_id} (${res.case.state}).`);
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Could not propose product');
    } finally {
      setLoading(false);
    }
  };

  const handleKernelVerify = async (product: Product) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.verifyCatalogUrl({
        product_id: product.product_id,
        url: product.url || undefined,
      });
      setUrlVerifications((prev) => ({ ...prev, [product.product_id]: res }));
    } catch (err) {
      setError(err instanceof MandateApiError ? err.message : 'Kernel URL verification failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <SectionHeader
        eyebrow="Catalog & Agent Proposals"
        title="Shopping & Proposals"
        subtitle="Browse merchant inventory, rank mandate-compliant candidates, run the zero-PayPal 2-tool Shopping Agent, or verify merchant URLs via Kernel."
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
      {notice && (
        <InfoBanner tone="verified">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span>{notice}</span>
            <Button size="sm" variant="primary" onClick={() => navigate('/app/cases')}>
              Open Cases
            </Button>
          </div>
        </InfoBanner>
      )}

      {/* Mandate & Search Controls */}
      <div className="surface-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12.5px' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Active Mandate:</span>
            <select
              value={selectedMandateId}
              onChange={(e) => setSelectedMandateId(e.target.value)}
              style={{
                padding: '7px 10px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                background: 'var(--bg-main)',
                fontSize: '13px',
              }}
            >
              {mandates.length === 0 && <option value="">No active mandate</option>}
              {mandates.map((m) => (
                <option key={m.mandate_id} value={m.mandate_id}>
                  {m.mandate_id} ({formatMoney(m.max_total)}) — {m.intent_text.slice(0, 40)}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12.5px' }}>
            <input type="checkbox" checked={verifiedOnly} onChange={(e) => setVerifiedOnly(e.target.checked)} />
            <span>Verified sellers only</span>
          </label>
        </div>

        <form onSubmit={handleCatalogSearch} style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ position: 'relative', flex: '1 1 260px' }}>
            <Search
              size={14}
              style={{ position: 'absolute', left: '11px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}
            />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search products (e.g. gift, candle, keyboard, espresso)..."
              style={{
                width: '100%',
                padding: '9px 12px 9px 32px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-subtle)',
                background: 'var(--bg-main)',
              }}
            />
          </div>
          <Button type="submit" variant="secondary" loading={loading}>
            Search Catalog
          </Button>
          <Button type="button" variant="primary" icon={<Sparkles size={14} />} loading={loading} onClick={handleAskPreference}>
            Rank for Mandate
          </Button>
          <Button type="button" variant="brass" icon={<Bot size={14} />} loading={loading} onClick={handleRunAgent}>
            Run 2-Tool Agent
          </Button>
        </form>
      </div>

      {/* Agent Trace */}
      {agentRun && (
        <div className="surface-card" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
            <span style={{ fontWeight: 600, fontSize: '13.5px' }}>
              Shopping Agent Execution (`POST /shopping/agent`)
            </span>
            <StatusPill tone="verified" mono>
              Tools: {agentRun.tools_exposed.join(', ')} (Zero PayPal tools)
            </StatusPill>
          </div>
          <div className="mono" style={{ fontSize: '11.5px', color: 'var(--text-secondary)' }}>
            Trace steps: {agentRun.tool_trace.length}
          </div>
        </div>
      )}

      {/* Ranked Candidates (if Run) */}
      {rankedOptions && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <h2 style={{ fontSize: '15px', fontWeight: 600 }}>
            Mandate-Ranked Candidates (`POST /shopping/options`)
          </h2>
          {rankedOptions.length === 0 ? (
            <EmptyState
              icon={<ShoppingBag size={18} />}
              title="No mandate-compliant candidates found"
              description="Try broadening your query or inspecting your active mandate constraints."
            />
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
              {rankedOptions.map((opt) => (
                <div
                  key={opt.product.product_id}
                  className="surface-card"
                  style={{ padding: '16px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: '12px' }}
                >
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                      <span className="mono" style={{ fontSize: '11px', color: 'var(--accent-brass)' }}>
                        Rank #{opt.index} · Score {opt.deterministic_score.toFixed(2)}
                      </span>
                      <StatusPill tone={opt.product.seller_verified ? 'verified' : 'danger'}>
                        {opt.product.seller_verified ? 'Verified' : 'Unverified'}
                      </StatusPill>
                    </div>
                    <h3 style={{ fontSize: '14.5px', fontWeight: 600 }}>{opt.product.title}</h3>
                    <div className="tabular" style={{ fontSize: '17px', fontWeight: 600, color: 'var(--accent-brass)', marginTop: '6px' }}>
                      {formatMoney(opt.product.price)}
                    </div>
                    <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '6px' }}>{opt.reason}</p>
                  </div>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setTarget({ kind: 'option', option: opt, mandateId: selectedMandateId })}
                    >
                      Inspect
                    </Button>
                    <Button
                      size="sm"
                      variant="brass"
                      loading={loading}
                      onClick={() => void handleProposePick(opt.product.product_id)}
                    >
                      Propose & Lock
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Full Catalog Grid */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <h2 style={{ fontSize: '15px', fontWeight: 600 }}>Catalog Inventory ({products.length})</h2>
        {products.length === 0 ? (
          <EmptyState
            icon={<ShoppingBag size={18} />}
            title="No matching products"
            description="Adjust your search term or clear the verified-only filter."
          />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
            {products.map((p) => {
              const kv = urlVerifications[p.product_id];
              return (
                <div
                  key={p.product_id}
                  className="surface-card"
                  style={{ padding: '16px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: '12px' }}
                >
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                      <span className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        {p.product_id}
                      </span>
                      <StatusPill tone={p.seller_verified ? 'verified' : 'danger'}>
                        {p.seller_verified ? 'Verified Seller' : 'Unverified Seller'}
                      </StatusPill>
                    </div>
                    <h3 style={{ fontSize: '14.5px', fontWeight: 600 }}>{p.title}</h3>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      {p.seller_name} ({p.seller_id}) · {p.category}
                    </div>
                    <div className="tabular" style={{ fontSize: '17px', fontWeight: 600, color: 'var(--accent-brass)', marginTop: '8px' }}>
                      {formatMoney(p.price)}
                    </div>
                    <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '6px' }}>
                      {p.description.slice(0, 120)}
                      {p.description.length > 120 ? '…' : ''}
                    </p>
                    {kv && (
                      <div
                        style={{
                          marginTop: '8px',
                          padding: '7px 9px',
                          borderRadius: 'var(--radius-xs)',
                          background: 'var(--bg-subtle)',
                          fontSize: '11.5px',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <span className="mono">Kernel ({kv.mode})</span>
                          <StatusPill tone={kv.verified ? 'verified' : 'warn'}>
                            {kv.verified ? 'URL Verified' : 'Unverified'}
                          </StatusPill>
                        </div>
                      </div>
                    )}
                  </div>

                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={<Globe size={12} />}
                      loading={loading}
                      onClick={() => void handleKernelVerify(p)}
                    >
                      Verify URL
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      icon={<ShieldCheck size={12} />}
                      loading={loading}
                      disabled={!p.in_stock}
                      onClick={() => void handleProposePick(p.product_id)}
                    >
                      Propose Case
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
