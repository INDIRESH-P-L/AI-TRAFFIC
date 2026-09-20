import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
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
                <Layout />
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
          </Route>

          {/* Catch-all */}
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
