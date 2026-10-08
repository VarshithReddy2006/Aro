import React, { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Role } from "./types/contracts";
import { apiClient } from "./api/client";
import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { CasesPage } from "./pages/CasesPage";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { EvidencePage } from "./pages/EvidencePage";
import { PoliciesPage } from "./pages/PoliciesPage";
import { SettingsPage } from "./pages/SettingsPage";

export const App: React.FC = () => {
  const [currentRole, setCurrentRole] = useState<Role>(Role.OPERATOR);

  const handleRoleChange = (role: Role) => {
    setCurrentRole(role);
    apiClient.currentUserRole = role;
  };

  return (
    <BrowserRouter>
      <AppShell
        currentRole={currentRole}
        onRoleChange={handleRoleChange}
        isDemoMode={true}
      >
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/cases" element={<CasesPage />} />
          <Route path="/cases/:caseId" element={<CaseDetailPage currentRole={currentRole} />} />
          <Route path="/evidence" element={<EvidencePage />} />
          <Route path="/policies" element={<PoliciesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
};

export default App;
