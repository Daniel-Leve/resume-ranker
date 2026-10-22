import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { ProtectedRoute, PublicOnlyRoute } from "@/components/shared/ProtectedRoute";
import { AppLayout } from "@/components/layout/AppLayout";
import { PublicLayout } from "@/components/layout/PublicLayout";
import { Toaster } from "@/components/ui/toaster";

// Auth Pages
import { SignInPage } from "@/pages/auth/SignInPage";
import { SignUpPage } from "@/pages/auth/SignUpPage";

// Recruiter Pages
import { DashboardPage } from "@/pages/recruiter/DashboardPage";
import { JobsPage } from "@/pages/recruiter/JobsPage";
import { NewJobPage } from "@/pages/recruiter/NewJobPage";
import { JobDetailPage } from "@/pages/recruiter/JobDetailPage";
import { CandidatesPage } from "@/pages/recruiter/CandidatesPage";
import { CandidateDeepDivePage } from "@/pages/recruiter/CandidateDeepDivePage";
import { ReviewQueuePage } from "@/pages/recruiter/ReviewQueuePage";
import { SettingsPage } from "@/pages/recruiter/SettingsPage";

// Candidate Portal Pages
import { ApplyPage } from "@/pages/candidate/ApplyPage";
import { TrackPage } from "@/pages/candidate/TrackPage";
import { FeedbackPage } from "@/pages/candidate/FeedbackPage";

// Root redirect handler
const IndexRedirect: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return null;
  return <Navigate to={isAuthenticated ? "/dashboard" : "/sign-in"} replace />;
};

export const App: React.FC = () => {
  return (
    <>
      <Routes>
        {/* Root Redirect */}
        <Route path="/" element={<IndexRedirect />} />

        {/* Auth routes */}
        <Route
          path="/sign-in"
          element={
            <PublicOnlyRoute>
              <SignInPage />
            </PublicOnlyRoute>
          }
        />
        <Route
          path="/sign-up"
          element={
            <PublicOnlyRoute>
              <SignUpPage />
            </PublicOnlyRoute>
          }
        />

        {/* Protected Recruiter Workspace */}
        <Route
          element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }
        >
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/new" element={<NewJobPage />} />
          <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          <Route path="/jobs/:jobId/candidates" element={<CandidatesPage />} />
          <Route
            path="/jobs/:jobId/candidates/:candidateId"
            element={<CandidateDeepDivePage />}
          />
          <Route path="/jobs/:jobId/review-queue" element={<ReviewQueuePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>

        {/* Public Candidate Portal */}
        <Route element={<PublicLayout />}>
          <Route path="/apply/:jobId" element={<ApplyPage />} />
          <Route path="/track" element={<TrackPage />} />
          <Route path="/feedback" element={<FeedbackPage />} />
        </Route>

        {/* Fallback route */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      {/* Global Notification Toast Container */}
      <Toaster />
    </>
  );
};

export default App;
