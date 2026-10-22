import { QueryClientProvider } from '@tanstack/react-query';
import { MotionConfig } from 'framer-motion';
import { queryClient } from './api/queries';
import { useEffect } from 'react';
import { DIAGNOSTIC_AREAS } from './config/categories';
import { BrowserRouter, Navigate, Route, Routes, useSearchParams } from 'react-router-dom';
import { RequireAuth } from './components/auth/RequireAuth';
import { AppLayout } from './components/layout/AppLayout';
import { ThemeProvider, useTheme } from './context/ThemeContext';
import { ToastProvider } from './context/ToastContext';
import AdminPage from './pages/AdminPage';
import MeasurePage from './pages/MeasurePage';
import ProblemPage from './pages/ProblemPage';
import AssessmentOverviewPage from './pages/AssessmentOverviewPage';
import CategoryPage from './pages/CategoryPage';
import ConnectionPage from './pages/ConnectionPage';
import DataExplorerPage from './pages/DataExplorerPage';
import SalesforceSetupPage from './pages/SalesforceSetupPage';
import DashboardPage from './pages/DashboardPage';
import PortfolioPage from './pages/PortfolioPage';
import DiagnosticAreaPage from './pages/DiagnosticAreaPage';
import OAuthCallbackPage from './pages/OAuthCallbackPage';
import HelpPage from './pages/HelpPage';
import HistoryPage from './pages/HistoryPage';
import HomePage from './pages/HomePage';
import LoginPage from './pages/LoginPage';
import NotFoundPage from './pages/NotFoundPage';
import ReportsPage from './pages/ReportsPage';
import ResultsPage from './pages/ResultsPage';
import SettingsPage from './pages/SettingsPage';

function MotionRoot({ children }: { children: React.ReactNode }) {
  const { reduceMotion } = useTheme();
  useEffect(() => {
    document.documentElement.classList.toggle('reduce-motion', reduceMotion);
  }, [reduceMotion]);
  return <MotionConfig reducedMotion={reduceMotion ? 'always' : 'user'}>{children}</MotionConfig>;
}

export default function App() {
  return (
    <ThemeProvider>
      <MotionRoot>
        <ToastProvider>
          <QueryClientProvider client={queryClient}>
            <BrowserRouter>
              <Routes>
                <Route index element={<HomePage />} />
                <Route path="login" element={<LoginPage />} />
                <Route
                  element={
                    <RequireAuth>
                      <AppLayout />
                    </RequireAuth>
                  }
                >
                  <Route path="dashboard" element={<DashboardPage />} />
                  <Route path="portfolio" element={<PortfolioPage />} />
                  <Route path="connection" element={<ConnectionPage />} />
                  <Route path="data" element={<DataExplorerPage />} />
                  <Route path="data/:objectName" element={<DataExplorerPage />} />
                  <Route path="connection/setup" element={<SalesforceSetupPage />} />
                  <Route path="connection/callback" element={<OAuthCallbackPage />} />
                  <Route path="assessment" element={<AssessmentOverviewPage />} />
                  <Route path="assessment/new" element={<LegacyNewCheckRedirect />} />
                  <Route path="assessment/:categoryId" element={<CategoryPage />} />
                  <Route path="assessment/:categoryId/:areaId" element={<DiagnosticAreaPage />} />
                  <Route path="results" element={<ResultsPage />} />
                  <Route path="problems/:findingId" element={<ProblemPage />} />
                  <Route path="measures/:areaId" element={<MeasurePage />} />
                  <Route path="reports" element={<ReportsPage />} />
                  <Route path="history" element={<HistoryPage />} />
                  <Route path="admin" element={<AdminPage />} />
                  <Route path="settings" element={<SettingsPage />} />
                  <Route path="help" element={<HelpPage />} />
                  <Route path="*" element={<NotFoundPage />} />
                </Route>
              </Routes>
            </BrowserRouter>
          </QueryClientProvider>
        </ToastProvider>
      </MotionRoot>
    </ThemeProvider>
  );
}

/** Checks now start on the topic, area, or "What We Check" page; keep old links working. */
function LegacyNewCheckRedirect() {
  const [params] = useSearchParams();
  const area = params.get('area');
  const category = params.get('category');
  const areaCategory = area ? DIAGNOSTIC_AREAS.find((a) => a.id === area)?.categoryId : undefined;
  const to = areaCategory ? `/assessment/${areaCategory}/${area}` : category ? `/assessment/${encodeURIComponent(category)}` : '/assessment';
  return <Navigate to={to} replace />;
}
