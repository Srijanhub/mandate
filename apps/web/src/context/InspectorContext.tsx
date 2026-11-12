import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { Case, LedgerEntry, Mandate, RankedOptionResponse } from '../api/types';

export type InspectorTarget =
  | { kind: 'none' }
  | { kind: 'mandate'; mandate: Mandate }
  | { kind: 'option'; option: RankedOptionResponse; mandateId?: string }
  | { kind: 'case'; caseData: Case }
  | { kind: 'ledger'; entry: LedgerEntry };

export interface RecentActivityItem {
  id: string;
  label: string;
  detail: string;
  timestamp: string;
  target?: InspectorTarget;
}

interface InspectorContextValue {
  target: InspectorTarget;
  setTarget: (target: InspectorTarget) => void;
  clearTarget: () => void;
  recentActivity: RecentActivityItem[];
  pushActivity: (item: Omit<RecentActivityItem, 'id' | 'timestamp'>) => void;
  mobileInspectorOpen: boolean;
  setMobileInspectorOpen: (open: boolean) => void;
}

const InspectorContext = createContext<InspectorContextValue | null>(null);

export const InspectorProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [target, setTargetState] = useState<InspectorTarget>({ kind: 'none' });
  const [recentActivity, setRecentActivity] = useState<RecentActivityItem[]>([]);
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false);

  const setTarget = useCallback((next: InspectorTarget) => {
    setTargetState(next);
  }, []);

  const clearTarget = useCallback(() => {
    setTargetState({ kind: 'none' });
  }, []);

  const pushActivity = useCallback((item: Omit<RecentActivityItem, 'id' | 'timestamp'>) => {
    setRecentActivity((prev) => {
      const entry: RecentActivityItem = {
        ...item,
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      return [entry, ...prev].slice(0, 8);
    });
  }, []);

  const value = useMemo(
    () => ({
      target,
      setTarget,
      clearTarget,
      recentActivity,
      pushActivity,
      mobileInspectorOpen,
      setMobileInspectorOpen,
    }),
    [target, setTarget, clearTarget, recentActivity, pushActivity, mobileInspectorOpen],
  );

  return <InspectorContext.Provider value={value}>{children}</InspectorContext.Provider>;
};

export function useInspector(): InspectorContextValue {
  const ctx = useContext(InspectorContext);
  if (!ctx) throw new Error('useInspector must be used inside InspectorProvider');
  return ctx;
}
