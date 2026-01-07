import { Navigate, Route, Routes } from "react-router-dom";

import { useSessionStore } from "./state/session";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { AppShell } from "./components/layout/AppShell";
import { SignalHubPage } from "./pages/SignalHubPage";
import { BacktestPage } from "./pages/BacktestPage";
import {
  InventoryPage,
  ExperimentsPage,
  CatalogPage,
  MLOpsPage,
  MonitorPage,
  RegimePage,
  DocsPage,
  AdminPage,
} from "./pages/PlaceholderPages";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { tenantId, principalId } = useSessionStore();
  if (!tenantId || !principalId) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

const App = () => {
  const { tenantId, principalId } = useSessionStore();

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      {/* Protected App Routes */}
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<HomePage />} />
        <Route path="signals" element={<SignalHubPage />} />
        <Route path="backtest" element={<BacktestPage />} />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="experiments" element={<ExperimentsPage />} />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="mlops" element={<MLOpsPage />} />
        <Route path="monitor" element={<MonitorPage />} />
        <Route path="regime" element={<RegimePage />} />
        <Route path="docs" element={<DocsPage />} />
        <Route path="admin" element={<AdminPage />} />
      </Route>

      {/* Default redirect */}
      <Route
        path="*"
        element={<Navigate to={tenantId && principalId ? "/app" : "/login"} replace />}
      />
    </Routes>
  );
};

export default App;
