import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, configureApiAuth } from '../api/client';
import type { AuthConfigResponse, AuthSessionResponse, AuthUserResponse } from '../api/types';

const TOKEN_STORAGE_KEY = 'mandate-session-token';

interface AuthContextValue {
  user: AuthUserResponse | null;
  token: string | null;
  config: AuthConfigResponse | null;
  loading: boolean;
  sessionExpiredNotice: boolean;
  isAuthenticated: boolean;
  refreshConfig: () => Promise<AuthConfigResponse | null>;
  applySession: (session: AuthSessionResponse) => void;
  refreshUser: () => Promise<AuthUserResponse | null>;
  logout: () => Promise<void>;
  clearExpiredNotice: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // Ignore storage errors
  }
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(readStoredToken);
  const tokenRef = React.useRef<string | null>(token);
  tokenRef.current = token;
  const [user, setUser] = useState<AuthUserResponse | null>(null);
  const [config, setConfig] = useState<AuthConfigResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [sessionExpiredNotice, setSessionExpiredNotice] = useState<boolean>(false);

  const handleUnauthorized = useCallback(() => {
    setToken((current) => {
      if (current) {
        setSessionExpiredNotice(true);
      }
      return null;
    });
    tokenRef.current = null;
    setUser(null);
    writeStoredToken(null);
  }, []);

  configureApiAuth(() => tokenRef.current, handleUnauthorized);

  const refreshConfig = useCallback(async (): Promise<AuthConfigResponse | null> => {
    try {
      const cfg = await api.authConfig();
      setConfig(cfg);
      return cfg;
    } catch {
      return null;
    }
  }, []);

  const refreshUser = useCallback(async (): Promise<AuthUserResponse | null> => {
    if (!token) {
      setUser(null);
      return null;
    }
    try {
      const profile = await api.me();
      setUser(profile);
      return profile;
    } catch {
      return null;
    }
  }, [token]);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      await refreshConfig();
      if (readStoredToken()) {
        try {
          const profile = await api.me();
          if (active) setUser(profile);
        } catch {
          if (active) {
            writeStoredToken(null);
            setToken(null);
            setUser(null);
          }
        }
      }
      if (active) setLoading(false);
    })();
    return () => {
      active = false;
    };
  }, [refreshConfig]);

  const applySession = useCallback((session: AuthSessionResponse) => {
    writeStoredToken(session.access_token);
    tokenRef.current = session.access_token;
    setToken(session.access_token);
    setUser(session.user);
    setSessionExpiredNotice(false);
  }, []);

  const logout = useCallback(async () => {
    try {
      if (tokenRef.current) await api.logout();
    } catch {
      // Stateless acknowledgment
    }
    writeStoredToken(null);
    tokenRef.current = null;
    setToken(null);
    setUser(null);
    setSessionExpiredNotice(false);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      config,
      loading,
      sessionExpiredNotice,
      isAuthenticated: Boolean(user && token),
      refreshConfig,
      applySession,
      refreshUser,
      logout,
      clearExpiredNotice: () => setSessionExpiredNotice(false),
    }),
    [user, token, config, loading, sessionExpiredNotice, refreshConfig, applySession, refreshUser, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
