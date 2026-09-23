import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ConsoleProvider } from './context/ConsoleContext';
import { Layout } from './components/Layout';
import { Login } from './pages/Login';
import { Dashboard } from './pages/Dashboard';
import { LiveMap } from './pages/LiveMap';
import { Intersections } from './pages/Intersections';
import { IntersectionDetail } from './pages/IntersectionDetail';
import { Signals } from './pages/Signals';
import { Cameras } from './pages/Cameras';
import { Sensors } from './pages/Sensors';
import { Incidents } from './pages/Incidents';
import { Emergency } from './pages/Emergency';
import { Transit } from './pages/Transit';
import { Predictions } from './pages/Predictions';
import { Analytics } from './pages/Analytics';
import { Corridors } from './pages/Corridors';
import { AiCopilot } from './pages/AiCopilot';
import { Devices } from './pages/Devices';
import { Maintenance } from './pages/Maintenance';
import { Audit } from './pages/Audit';
import { Settings } from './pages/Settings';
import { Users } from './pages/Users';
import { ProviderHealth } from './pages/ProviderHealth';
import { AlertRules } from './pages/AlertRules';
import { Optimizer } from './pages/Optimizer';
import { Governance } from './pages/Governance';
import { DataTrust } from './pages/DataTrust';
import { Stringline } from './pages/Stringline';
import { ShiftHandover } from './pages/ShiftHandover';

const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--its-bg-app)',
          color: 'var(--its-text-muted)',
          fontSize: 'var(--text-sm)',
        }}
      >
        Verifying cryptographic session token...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />

          {/* Protected Console Routes */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <ConsoleProvider>
                  <Layout />
                </ConsoleProvider>
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="live-map" element={<LiveMap />} />
            <Route path="intersections" element={<Intersections />} />
            <Route path="intersections/:id" element={<IntersectionDetail />} />
            <Route path="signals" element={<Signals />} />
            <Route path="cameras" element={<Cameras />} />
            <Route path="sensors" element={<Sensors />} />
            <Route path="incidents" element={<Incidents />} />
            <Route path="emergency" element={<Emergency />} />
            <Route path="transit" element={<Transit />} />
            <Route path="predictions" element={<Predictions />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="corridors" element={<Corridors />} />
            <Route path="ai-copilot" element={<AiCopilot />} />
            <Route path="devices" element={<Devices />} />
            <Route path="maintenance" element={<Maintenance />} />
            <Route path="audit" element={<Audit />} />
            <Route path="settings" element={<Settings />} />
            <Route path="users" element={<Users />} />

            {/* Phase 2: backend intelligence surfaces */}
            <Route path="provider-health" element={<ProviderHealth />} />
            <Route path="alert-rules" element={<AlertRules />} />
            <Route path="optimizer" element={<Optimizer />} />
            <Route path="governance" element={<Governance />} />

            {/* Phase 3: operator insight */}
            <Route path="data-trust" element={<DataTrust />} />
            <Route path="stringline" element={<Stringline />} />
            <Route path="handover" element={<ShiftHandover />} />
          </Route>

          {/* Catch-all */}
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
