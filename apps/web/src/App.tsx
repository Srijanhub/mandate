import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { AppShell } from './components/layout/AppShell';
import { PhotonKnot } from './components/three/PhotonKnot';
import { InspectorProvider } from './context/InspectorContext';
import { AuthPage } from './pages/AuthPage';
import { CasesPage } from './pages/CasesPage';
import { CommandCentrePage } from './pages/CommandCentrePage';
import { DemoLabPage } from './pages/DemoLabPage';
import { LandingPage } from './pages/LandingPage';
import { LedgerPage } from './pages/LedgerPage';
import { MandatesPage } from './pages/MandatesPage';
import { OverviewPage } from './pages/OverviewPage';
import { SettingsPage } from './pages/SettingsPage';
import { ShoppingPage } from './pages/ShoppingPage';
import { TrustPage } from './pages/TrustPage';
import { ThemeProvider } from './theme/ThemeProvider';

const ProtectedAppGate: React.FC = () => {
  const { loading, config, isAuthenticated } = useAuth();

  if (loading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'grid',
          placeItems: 'center',
          background: 'var(--bg-main)',
        }}
      >
        <div style={{ width: '120px', height: '120px', textAlign: 'center' }}>
          <PhotonKnot variant="mini" interactive={false} />
          <div className="mono" style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '8px' }}>
            Initializing Mandate…
          </div>
        </div>
      </div>
    );
  }

  if (config?.require_auth && !isAuthenticated) {
    return <Navigate to="/auth" replace />;
  }

  return <AppShell />;
};

export const App: React.FC = () => (
  <ThemeProvider>
    <AuthProvider>
      <InspectorProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/auth" element={<AuthPage />} />

            <Route path="/app" element={<ProtectedAppGate />}>
              <Route index element={<Navigate to="/app/command-centre" replace />} />
              <Route path="overview" element={<OverviewPage />} />
              <Route path="command-centre" element={<CommandCentrePage />} />
              <Route path="mandates" element={<MandatesPage />} />
              <Route path="shopping" element={<ShoppingPage />} />
              <Route path="cases" element={<CasesPage />} />
              <Route path="ledger" element={<LedgerPage />} />
              <Route path="trust" element={<TrustPage />} />
              <Route path="demo-lab" element={<DemoLabPage />} />
              <Route path="settings" element={<SettingsPage />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </InspectorProvider>
    </AuthProvider>
  </ThemeProvider>
);

export default App;
