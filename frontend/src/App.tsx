import React, { useState, useEffect } from 'react';
import { AppShell } from './components/layout/AppShell';
import { OverviewPage } from './pages/OverviewPage';
import { JobsPage } from './pages/JobsPage';
import { JobWorkspacePage } from './pages/JobWorkspacePage';
import { ScreeningRunsPage } from './pages/ScreeningRunsPage';
import { SettingsPage } from './pages/SettingsPage';
import { LoginPage } from './components/auth/LoginPage';

import { CreateJobModal } from './features/jobs/CreateJobModal';
import { CandidateUploaderModal } from './features/candidates/CandidateUploaderModal';
import { ConfigModal } from './components/common/ConfigModal';

import { listJobs, listApplications, deleteJobPosting, decrementJobApplicationCount } from './api/jobs';
import { getDefaultTenant } from './api/tenants';
import { triggerScreening, getScreeningResults } from './api/screening';
import { CandidatePortalPage } from './pages/CandidatePortalPage';
import { Job, ScreeningRun, Application, UserRole } from './types';
import { removeStudentApplication, removeStudentApplicationsForJob } from './utils/studentStore';
import { UserSession, getStoredSession, clearSession } from './utils/authStore';

import { registerCandidateName } from './utils/formatters';

export function App() {
  const [userSession, setUserSession] = useState<UserSession | null>(() => getStoredSession());
  const [userRole, setUserRole] = useState<UserRole>(() => {
    const session = getStoredSession();
    if (session?.role) return session.role;
    return (localStorage.getItem('resume_ranker_user_role') as UserRole) || 'recruiter';
  });
  const [activeNav, setActiveNav] = useState<string>(() => {
    const savedRole = localStorage.getItem('resume_ranker_user_role');
    const defaultNav = savedRole === 'candidate' ? 'candidate-portal' : 'overview';
    return localStorage.getItem('resume_ranker_active_nav') || defaultNav;
  });

  const [jobs, setJobs] = useState<Job[]>([]);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [screeningRun, setScreeningRun] = useState<ScreeningRun | null>(null);
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState<boolean>(false);

  // Modals
  const [isCreateJobOpen, setIsCreateJobOpen] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [isConfigOpen, setIsConfigOpen] = useState(false);

  const handleLogin = (session: UserSession) => {
    setUserSession(session);
    setUserRole(session.role);
    if (session.role === 'candidate') {
      handleNavigate('candidate-portal');
    } else {
      handleNavigate('overview');
    }
  };

  const handleLogout = () => {
    clearSession();
    setUserSession(null);
  };

  const handleDeleteJob = (jobId: string) => {
    deleteJobPosting(jobId);
    removeStudentApplicationsForJob(jobId);
    setJobs(prev => prev.filter(j => j.job_id !== jobId));
    if (activeJob?.job_id === jobId) {
      setActiveJob(null);
      localStorage.removeItem('resume_ranker_active_job_id');
      handleNavigate('jobs');
    }
  };

  const handleDeleteCandidate = (candidateIdOrAppId: string) => {
    removeStudentApplication(candidateIdOrAppId);
    if (screeningRun) {
      setScreeningRun({
        ...screeningRun,
        candidates: (screeningRun.candidates || []).filter(
          c => c.candidate_id !== candidateIdOrAppId && c.source_key !== candidateIdOrAppId
        ),
        candidate_count: Math.max(0, (screeningRun.candidate_count || 1) - 1)
      });
    }
    setApplications(prev => prev.filter(a => a.application_id !== candidateIdOrAppId));
    if (activeJob) {
      decrementJobApplicationCount(activeJob.job_id);
    }
  };

  // Load Initial Jobs & restore active job selection
  useEffect(() => {
    async function loadJobs() {
      try {
        const list = await listJobs();
        setJobs(list);
        if (list.length > 0) {
          const savedJobId = localStorage.getItem('resume_ranker_active_job_id');
          const found = list.find(j => j.job_id === savedJobId);
          setActiveJob(found || list[0]);
        }
      } catch (err) {
        console.error("Failed to fetch jobs list", err);
      }
    }
    loadJobs();
  }, []);

  // Save activeNav to localStorage
  const handleNavigate = (page: string) => {
    setActiveNav(page);
    localStorage.setItem('resume_ranker_active_nav', page);
  };

  // Role Toggle Switcher
  const handleToggleRole = (role: UserRole) => {
    setUserRole(role);
    localStorage.setItem('resume_ranker_user_role', role);
    if (role === 'candidate') {
      handleNavigate('candidate-portal');
    } else {
      handleNavigate('overview');
    }
  };

  // Poll / Fetch Screening Results and Applications when activeJob changes
  const fetchResults = async () => {
    if (!activeJob) return;
    setLoading(true);
    try {
      const [res, apps] = await Promise.all([
        getScreeningResults(activeJob.job_id),
        listApplications(activeJob.job_id)
      ]);
      if (res) {
        setScreeningRun(res);
        // Register candidate names returned from backend if present
        if (res.candidates && res.candidates.length > 0) {
          res.candidates.forEach(c => {
            if (c.candidate_name && !c.candidate_name.includes('saas__')) {
              registerCandidateName(c.candidate_id, c.candidate_name);
              if (c.source_key) registerCandidateName(c.source_key, c.candidate_name);
            }
          });
        }
      }
      if (apps) {
        setApplications(apps);
      }
    } catch (err) {
      console.warn("Failed to fetch workspace data", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeJob) {
      localStorage.setItem('resume_ranker_active_job_id', activeJob.job_id);
      fetchResults();
    }
  }, [activeJob]);

  // Polling loop when screening run status is active
  useEffect(() => {
    if (screeningRun?.status === 'RUNNING' || screeningRun?.status === 'RUNNING_PHASE2' || screeningRun?.status === 'RUNNING_PHASE3' || screeningRun?.status === 'QUEUED') {
      const interval = setInterval(() => {
        fetchResults();
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [screeningRun?.status, activeJob]);

  const handleOpenWorkspace = (job: Job) => {
    setActiveJob(job);
    localStorage.setItem('resume_ranker_active_job_id', job.job_id);
    handleNavigate('job-workspace');
  };

  const handleTriggerScreening = async () => {
    if (!activeJob) return;
    setScreeningRun((prev) => prev ? { ...prev, status: 'QUEUED' } : {
      screening_run_id: `run-${Date.now()}`,
      tenant_id: activeJob.tenant_id,
      job_id: activeJob.job_id,
      status: 'QUEUED',
      created_at: new Date().toISOString()
    });

    try {
      await triggerScreening(activeJob.job_id);
      fetchResults();
    } catch (err: any) {
      console.error("Screening trigger failed", err);
    }
  };

  const handleJobCreated = (newJob: Job) => {
    setJobs([newJob, ...jobs]);
    setActiveJob(newJob);
    localStorage.setItem('resume_ranker_active_job_id', newJob.job_id);
    handleNavigate('job-workspace');
  };

  // Filter jobs by logged in recruiter session
  const visibleJobs = userRole === 'recruiter' && userSession?.email
    ? jobs.filter(j => j.recruiter_email
        ? j.recruiter_email.toLowerCase() === userSession.email.toLowerCase()
        : userSession.email.toLowerCase() === 'recruiter@acme.com'
      )
    : jobs;

  useEffect(() => {
    if (userRole === 'recruiter') {
      if (visibleJobs.length > 0) {
        if (!activeJob || !visibleJobs.some(j => j.job_id === activeJob.job_id)) {
          setActiveJob(visibleJobs[0]);
        }
      } else {
        setActiveJob(null);
      }
    }
  }, [userSession?.email, userRole, jobs]);

  const tenant = getDefaultTenant();

  if (!userSession || !userSession.isAuthenticated) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return (
    <AppShell
      activeNav={activeNav}
      userRole={userRole}
      session={userSession}
      onNavigate={(page) => handleNavigate(page)}
      onToggleRole={handleToggleRole}
      onOpenConfig={() => setIsConfigOpen(true)}
      onLogout={handleLogout}
    >
      {userRole === 'candidate' ? (
        activeNav === 'settings' ? (
          <SettingsPage
            onOpenConfig={() => setIsConfigOpen(true)}
            session={userSession}
          />
        ) : (
          <CandidatePortalPage
            jobs={jobs}
            screeningRun={screeningRun}
            session={userSession}
            activeNav={activeNav}
            onNavigate={(p) => handleNavigate(p)}
            onApplyForJob={(job) => {
              setActiveJob(job);
              setIsUploadOpen(true);
            }}
          />
        )
      ) : (
        <>
          {activeNav === 'overview' && (
            <OverviewPage
              jobs={visibleJobs}
              screeningRun={screeningRun}
              onOpenJobWorkspace={handleOpenWorkspace}
              onOpenCreateJob={() => setIsCreateJobOpen(true)}
              onNavigate={(p) => handleNavigate(p)}
            />
          )}

          {activeNav === 'jobs' && (
            <JobsPage
              jobs={visibleJobs}
              onOpenJobWorkspace={handleOpenWorkspace}
              onOpenCreateJob={() => setIsCreateJobOpen(true)}
              onDeleteJob={handleDeleteJob}
            />
          )}

          {activeNav === 'job-workspace' && activeJob && (
            <JobWorkspacePage
              job={activeJob}
              screeningRun={screeningRun}
              applications={applications}
              onTriggerScreening={handleTriggerScreening}
              onRefresh={fetchResults}
              onOpenUpload={() => setIsUploadOpen(true)}
              loading={loading}
              onDeleteJob={handleDeleteJob}
              onDeleteCandidate={handleDeleteCandidate}
            />
          )}

          {activeNav === 'screening-runs' && (
            <ScreeningRunsPage
              screeningRun={screeningRun}
              jobs={visibleJobs}
              onOpenJobWorkspace={handleOpenWorkspace}
            />
          )}

          {activeNav === 'settings' && (
            <SettingsPage
              onOpenConfig={() => setIsConfigOpen(true)}
              session={userSession}
            />
          )}
        </>
      )}

      {/* Modals */}
      <CreateJobModal
        isOpen={isCreateJobOpen}
        onClose={() => setIsCreateJobOpen(false)}
        tenantId={tenant.tenant_id}
        recruiterEmail={userSession?.email}
        recruiterName={userSession?.name}
        onJobCreated={handleJobCreated}
      />

      <CandidateUploaderModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        activeJob={activeJob}
        session={userSession}
        onUploadSuccess={fetchResults}
      />

      <ConfigModal
        isOpen={isConfigOpen}
        onClose={() => setIsConfigOpen(false)}
      />
    </AppShell>
  );
}

export default App;
