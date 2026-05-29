import { Routes, Route, Navigate } from "react-router-dom";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { DashboardPage } from "@/pages/DashboardPage";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { ProjectDetailPage } from "@/pages/ProjectDetailPage";
import { AllBidsPage } from "@/pages/AllBidsPage";
import { BidDetailPage } from "@/pages/BidDetailPage";
import { CompareSessionPage } from "@/pages/CompareSessionPage";
import { RejectedEmailsPage } from "@/pages/RejectedEmailsPage";
import { EmailAccountsPage } from "@/pages/EmailAccountsPage";

/**
 * App — the authenticated application shell and route table.
 *
 * The whole tree sits behind ProtectedRoute (Entra SSO). Layout is a fixed
 * sidebar + header with a scrollable main region; each route renders inside an
 * ErrorBoundary so one page's failure can't take down navigation. The
 * comparison session route is the product centrepiece and gets the full main
 * region (it manages its own internal scroll via fullBleed PageShell).
 */
export default function App() {
  return (
    <ProtectedRoute>
      <div className="flex h-screen overflow-hidden bg-background">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header />
          <main className="min-h-0 flex-1 overflow-hidden">
            <ErrorBoundary>
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/projects" element={<ProjectsPage />} />
                <Route
                  path="/projects/:projectId"
                  element={<ProjectDetailPage />}
                />
                <Route
                  path="/projects/:projectId/compare/:sessionId"
                  element={<CompareSessionPage />}
                />
                <Route path="/bids" element={<AllBidsPage />} />
                <Route path="/bids/:bidId" element={<BidDetailPage />} />
                <Route path="/rejected" element={<RejectedEmailsPage />} />
                <Route
                  path="/email-accounts"
                  element={<EmailAccountsPage />}
                />
                {/* Unknown paths fall back to the dashboard. */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </ProtectedRoute>
  );
}
