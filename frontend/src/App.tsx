import React, { useState, useEffect } from 'react';
import { AppShell } from './components/layout/AppShell';
import { OverviewPage } from './pages/OverviewPage';
import { JobsPage } from './pages/JobsPage';
import { JobWorkspacePage } from './pages/JobWorkspacePage';
import { ScreeningRunsPage } from './pages/ScreeningRunsPage';
import { SettingsPage } from './pages/SettingsPage';

import { CreateJobModal } from './features/jobs/CreateJobModal';
import { CandidateUploaderModal } from './features/candidates/CandidateUploaderModal';
import { ConfigModal } from './components/common/ConfigModal';

import { listJobs, listApplications } from './api/jobs';
import { getDefaultTenant } from './api/tenants';
import { triggerScreening, getScreeningResults } from './api/screening';
import { Job, ScreeningRun, Application } from './types';

import { registerCandidateName } from './utils/formatters';

export function App() {
  const [activeNav, setActiveNav] = useState<string>(() => {
    return localStorage.getItem('resume_ranker_active_nav') || 'overview';
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

  // Poll / Fetch Screening Results when activeJob changes
  const fetchResults = async () => {
    if (!activeJob) return;
    setLoading(true);
    try {
      const res = await getScreeningResults(activeJob.job_id);
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

  const tenant = getDefaultTenant();

  return (
    <AppShell
      activeNav={activeNav}
      onNavigate={(page) => handleNavigate(page)}
      onOpenConfig={() => setIsConfigOpen(true)}
    >
      {activeNav === 'overview' && (
        <OverviewPage
          jobs={jobs}
          screeningRun={screeningRun}
          onOpenJobWorkspace={handleOpenWorkspace}
          onOpenCreateJob={() => setIsCreateJobOpen(true)}
          onNavigate={(p) => handleNavigate(p)}
        />
      )}

      {activeNav === 'jobs' && (
        <JobsPage
          jobs={jobs}
          onOpenJobWorkspace={handleOpenWorkspace}
          onOpenCreateJob={() => setIsCreateJobOpen(true)}
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
        />
      )}

      {activeNav === 'screening-runs' && (
        <ScreeningRunsPage
          screeningRun={screeningRun}
          jobs={jobs}
          onOpenJobWorkspace={handleOpenWorkspace}
        />
      )}

      {activeNav === 'settings' && (
        <SettingsPage
          onOpenConfig={() => setIsConfigOpen(true)}
        />
      )}

      {/* Modals */}
      <CreateJobModal
        isOpen={isCreateJobOpen}
        onClose={() => setIsCreateJobOpen(false)}
        tenantId={tenant.tenant_id}
        onJobCreated={handleJobCreated}
      />

      <CandidateUploaderModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        activeJob={activeJob}
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
