import { Navigate, Route, Routes } from "react-router-dom";

import { useSessionStore } from "./state/session";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";

const App = () => {
  const { tenantId, principalId } = useSessionStore();

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/app"
        element={
          tenantId && principalId ? (
            <HomePage />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
      <Route
        path="*"
        element={<Navigate to={tenantId && principalId ? "/app" : "/login"} replace />}
      />
    </Routes>
  );
};

export default App;
