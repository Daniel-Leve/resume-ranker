import { apiRequest, isMockMode } from './client';
import { Job, CreateJobInput, Application } from '../types';
import { MOCK_JOBS } from '../fixtures/mockData';

const CREATED_JOBS_KEY = 'resume_ranker_created_jobs';

export function getCreatedJobs(): Job[] {
  try {
    const raw = localStorage.getItem(CREATED_JOBS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveCreatedJob(job: Job): void {
  try {
    const existing = getCreatedJobs().filter(j => j.job_id !== job.job_id);
    const updated = [job, ...existing];
    localStorage.setItem(CREATED_JOBS_KEY, JSON.stringify(updated));
  } catch {
    // Ignore storage errors
  }
}

export async function createJob(tenantId: string, input: CreateJobInput): Promise<Job> {
  const jobPayload = {
    title: input.title,
    description: input.description,
  };

  let newJob: Job;

  if (isMockMode()) {
    newJob = {
      job_id: `job-${Date.now()}`,
      tenant_id: tenantId || "tenant-acme-corp",
      title: input.title,
      description: input.description,
      department: input.department || "Engineering",
      location: input.location || "Remote",
      status: "OPEN",
      application_count: 0,
      created_at: new Date().toISOString()
    };
    MOCK_JOBS.unshift(newJob);
  } else {
    const res = await apiRequest<Job>(`/tenants/${tenantId}/jobs`, {
      method: "POST",
      body: JSON.stringify(jobPayload),
    });

    newJob = {
      ...res,
      description: input.description,
      department: input.department || "Engineering",
      location: input.location || "Remote",
    };
  }

  saveCreatedJob(newJob);
  return newJob;
}

export async function getJob(tenantId: string, jobId: string): Promise<Job> {
  const created = getCreatedJobs().find(j => j.job_id === jobId);
  if (created) return created;

  if (isMockMode()) {
    const found = MOCK_JOBS.find(j => j.job_id === jobId);
    if (!found) throw new Error(`Job not found: ${jobId}`);
    return found;
  }
  return apiRequest<Job>(`/tenants/${tenantId}/jobs/${jobId}`);
}

export async function listJobs(tenantId: string = "tenant-acme-corp"): Promise<Job[]> {
  const createdJobs = getCreatedJobs();

  if (isMockMode()) {
    const combined = [...createdJobs];
    for (const mj of MOCK_JOBS) {
      if (!combined.some(j => j.job_id === mj.job_id)) {
        combined.push(mj);
      }
    }
    return combined;
  }

  try {
    const res = await apiRequest<{ tenant_id: string; jobs: Job[] }>(`/tenants/${tenantId}/jobs`);
    if (res && Array.isArray(res.jobs) && res.jobs.length > 0) {
      const combined = [...createdJobs];
      for (const bj of res.jobs) {
        if (!combined.some(j => j.job_id === bj.job_id)) {
          combined.push(bj);
        }
      }
      return combined;
    }
  } catch (err) {
    // If backend bulk list endpoint is absent, return persistent created jobs + seed jobs
  }

  const combined = [...createdJobs];
  for (const mj of MOCK_JOBS) {
    if (!combined.some(j => j.job_id === mj.job_id)) {
      combined.push(mj);
    }
  }
  return combined;
}

export async function listApplications(jobId: string): Promise<Application[]> {
  if (isMockMode()) {
    return [];
  }
  try {
    const res = await apiRequest<{ job_id: string; applications: Application[] }>(`/jobs/${jobId}/applications`);
    if (res && Array.isArray(res.applications)) {
      return res.applications;
    }
  } catch (err) {
    // If backend does not have GET applications endpoint, return empty list cleanly
  }
  return [];
}
