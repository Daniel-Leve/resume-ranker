import { getIdToken, isTokenValid, refreshSession, getCurrentUser } from "./auth";

const BASE_URL = import.meta.env.VITE_API_URL || "https://vxbiq8rt27.execute-api.ap-south-1.amazonaws.com/dev";

export interface ApiError extends Error {
  status?: number;
  data?: any;
}

export async function apiFetch<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const cleanEndpoint = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const url = `${BASE_URL}${cleanEndpoint}`;

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  // Auto-inject JWT token if available
  const token = getIdToken();
  if (token) {
    if (!isTokenValid()) {
      await refreshSession();
    }
    const freshToken = getIdToken();
    if (freshToken) {
      headers["Authorization"] = `Bearer ${freshToken}`;
    }
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 204) {
    return {} as T;
  }

  const text = await response.text();
  let data: any = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }

  if (!response.ok) {
    const error = new Error(
      data.message || data.error || `HTTP ${response.status}: ${response.statusText}`
    ) as ApiError;
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data as T;
}

// -------------------- Models --------------------

export interface Criterion {
  id: string;
  name: string;
  type: "MUST_HAVE" | "NICE_TO_HAVE" | string;
  weight: number;
  description: string;
}

export interface Rubric {
  rubric_id?: string;
  job_id?: string;
  status: "DRAFT" | "APPROVED" | string;
  criteria: Criterion[];
  created_at?: string;
  updated_at?: string;
}

export interface Job {
  job_id: string;
  tenant_id?: string;
  title: string;
  location?: string;
  description: string;
  status: "OPEN" | "CLOSED" | "ARCHIVED" | string;
  created_at: string;
  applications_count?: number;
  shortlisted_count?: number;
  review_queue_count?: number;
  rubric_status?: "NONE" | "DRAFT" | "APPROVED" | string;
  rubric?: Rubric;
  screening_status?: "IDLE" | "IN_PROGRESS" | "COMPLETED" | "FAILED" | string;
  phase3_status?: string;
  phase4_status?: string;
}

export interface Candidate {
  candidate_id: string;
  job_id: string;
  name: string;
  email: string;
  score: number;
  decision: "SHORTLISTED" | "NEEDS_REVIEW" | "REJECTED" | "UNDECIDED" | string;
  rank?: number;
  s3_resume_key?: string;
  created_at?: string;
  strengths?: string[];
  gaps?: string[];
  flag_reasons?: string[];
}

export interface CriteriaBreakdown {
  criterion: string;
  score: number;
  evidence: string;
}

export interface InterviewQuestion {
  question: string;
  purpose?: string;
}

export interface CandidateReport extends Candidate {
  criteria_breakdown?: CriteriaBreakdown[];
  strengths: string[];
  gaps: string[];
  risks?: string[];
  interview_questions?: InterviewQuestion[];
}

export interface ReviewQueueItem {
  candidate_id: string;
  job_id: string;
  candidate_name: string;
  email?: string;
  flag_reasons: string[];
  risk_level: "LOW" | "MEDIUM" | "HIGH" | string;
  weighted_score: number;
  notes?: string;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  tenant_id: string;
  tenant_name?: string;
  role?: string;
  plan?: string;
  tenants?: any[];
}

export interface ApplicationInitResponse {
  application_id: string;
  candidate_access_token: string;
  upload_url: string;
}

export interface ApplicationTrackStatus {
  application_id: string;
  job_id: string;
  candidate_name?: string;
  overall_status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | string;
  steps: {
    s3_upload: "pending" | "running" | "done" | "error";
    phase1_extraction: "pending" | "running" | "done" | "error";
    phase2_indexing: "pending" | "running" | "done" | "error";
    phase3_4_screening: "pending" | "running" | "done" | "error";
  };
  step_messages?: Record<string, string>;
  updated_at?: string;
}

export interface CandidateFeedback {
  application_id: string;
  job_id: string;
  candidate_name: string;
  job_title?: string;
  decision: "SHORTLISTED" | "REJECTED" | "NEEDS_REVIEW" | "PENDING";
  strengths: string[];
  gaps: string[];
  recommendations?: string[];
  message?: string;
}

// -------------------- Endpoints --------------------

const TENANT_KEY = "recruitai_tenant_id";

export async function getTenantId(): Promise<string> {
  const cached = localStorage.getItem(TENANT_KEY);
  if (cached) return cached;

  try {
    const me = await api.getMe();
    if (me.tenant_id) {
      localStorage.setItem(TENANT_KEY, me.tenant_id);
      return me.tenant_id;
    }
  } catch (err) {
    console.warn("Failed to fetch /me for tenant ID:", err);
  }

  // Fallback: If no tenant found for user, try auto-provisioning one
  try {
    const user = getCurrentUser();
    const companyName = user?.name ? `${user.name}'s Org` : "Workspace Org";
    const res = await apiFetch<{ tenant_id: string }>("/tenants", {
      method: "POST",
      body: JSON.stringify({ name: companyName }),
    });
    if (res?.tenant_id) {
      localStorage.setItem(TENANT_KEY, res.tenant_id);
      return res.tenant_id;
    }
  } catch (err) {
    console.error("Failed to auto-create tenant:", err);
  }

  throw new Error("Unable to resolve organization workspace / tenant_id.");
}

export const api = {
  // Jobs
  getJobs: async (): Promise<Job[]> => {
    const tenantId = await getTenantId();
    const res = await apiFetch<{ jobs?: Job[] } | Job[]>(`/tenants/${tenantId}/jobs`);
    if (Array.isArray(res)) return res;
    return res.jobs || [];
  },

  createJob: async (payload: { title: string; location?: string; description: string; shortlisted_count?: number }): Promise<Job> => {
    const tenantId = await getTenantId();
    return await apiFetch<Job>(`/tenants/${tenantId}/jobs`, {
      method: "POST",
      body: JSON.stringify({
        title: payload.title,
        description: payload.description,
        final_shortlisted_candidates_count: payload.shortlisted_count || 5,
      }),
    });
  },

  getJob: async (jobId: string): Promise<Job> => {
    const cachedTenant = localStorage.getItem(TENANT_KEY);
    if (cachedTenant) {
      try {
        return await apiFetch<Job>(`/tenants/${cachedTenant}/jobs/${jobId}`);
      } catch {
        // Fall back to public endpoint
      }
    }
    return await apiFetch<Job>(`/jobs/${jobId}`);
  },

  // Rubric
  generateRubric: (jobId: string) =>
    apiFetch<Rubric>(`/jobs/${jobId}/rubric`, {
      method: "POST",
    }),

  approveRubric: (jobId: string) =>
    apiFetch<Rubric>(`/jobs/${jobId}/rubric/approve`, {
      method: "POST",
    }),

  // Screening
  runScreening: (jobId: string, shortlistCount: number = 5) =>
    apiFetch<{ status: string; message?: string }>(`/jobs/${jobId}/screening`, {
      method: "POST",
      body: JSON.stringify({ shortlist_count: shortlistCount }),
    }),

  getScreeningStatus: (jobId: string) =>
    apiFetch<{
      status: string;
      phase3_status?: string;
      phase4_status?: string;
      processed_count?: number;
      total_count?: number;
    }>(`/jobs/${jobId}/screening-status`),

  // Candidates / Applications
  getCandidates: async (jobId: string): Promise<Candidate[]> => {
    const res = await apiFetch<{ applications?: any[] } | any[]>(`/jobs/${jobId}/applications`);
    const apps = Array.isArray(res) ? res : res.applications || [];
    return apps.map((app: any, idx: number) => ({
      candidate_id: app.candidate_id || app.application_id,
      application_id: app.application_id,
      job_id: app.job_id || jobId,
      name: app.candidate_name || app.name || "Candidate",
      email: app.email || "",
      score: app.hr_report?.final_score ?? app.hr_report?.rerank_score ?? (app.decision === "SHORTLISTED" ? 85 : 0),
      decision: app.decision || app.status || "UNDECIDED",
      rank: app.hr_report?.rerank_rank ?? idx + 1,
      s3_resume_key: app.s3_resume_key,
      created_at: app.created_at,
      strengths: app.hr_report?.strengths || [],
      gaps: app.hr_report?.gaps || [],
      flag_reasons: app.hr_report?.risks || [],
    }));
  },

  getCandidate: async (jobId: string, candidateId: string): Promise<CandidateReport> => {
    try {
      const report = await apiFetch<any>(`/jobs/${jobId}/candidates/${candidateId}/report`);
      return {
        candidate_id: report.candidate_id || candidateId,
        job_id: report.job_id || jobId,
        name: report.candidate_name || "Candidate",
        email: report.email || "",
        score: report.final_score ?? report.rerank_score ?? 0,
        decision: report.decision || "UNDECIDED",
        rank: report.rerank_rank,
        s3_resume_key: report.s3_resume_key,
        criteria_breakdown: (report.criteria_scores || report.match_matrix || []).map((c: any) => ({
          criterion: c.criterion_name || c.description || c.criterion_id,
          score: c.score ?? (c.status === "evidenced" ? 1 : 0),
          evidence: c.evidence_quote || (c.quotes && c.quotes[0]) || "Not evidenced",
        })),
        strengths: report.strengths || [],
        gaps: report.gaps || [],
        risks: report.risks || [],
        interview_questions: (report.interview_questions || []).map((q: any) =>
          typeof q === "string" ? { question: q } : q
        ),
      };
    } catch {
      // Fallback to application document if report is not yet generated
      const app = await apiFetch<any>(`/jobs/${jobId}/applications/${candidateId}`).catch(() => null);
      if (app) {
        const hr = app.hr_report || {};
        return {
          candidate_id: app.candidate_id || candidateId,
          job_id: app.job_id || jobId,
          name: app.candidate_name || "Candidate",
          email: app.email || "",
          score: hr.final_score ?? hr.rerank_score ?? 0,
          decision: app.decision || app.status || "UNDECIDED",
          rank: hr.rerank_rank,
          s3_resume_key: app.s3_resume_key,
          strengths: hr.strengths || [],
          gaps: hr.gaps || [],
          risks: hr.risks || [],
          interview_questions: (hr.interview_questions || []).map((q: any) =>
            typeof q === "string" ? { question: q } : q
          ),
        };
      }
      throw new Error(`Report for candidate ${candidateId} not found.`);
    }
  },

  // Review Queue
  getReviewQueue: async (jobId: string): Promise<ReviewQueueItem[]> => {
    const res = await apiFetch<{ items?: any[] } | any[]>(`/jobs/${jobId}/review-queue`);
    const rawItems = Array.isArray(res) ? res : res.items || [];
    return rawItems.map((item: any) => ({
      candidate_id: item.candidate_id || item.application_id,
      job_id: item.job_id || jobId,
      candidate_name: item.candidate_name || item.name || "Candidate",
      email: item.email || "",
      flag_reasons: item.flag_reasons || item.risks || [],
      risk_level: item.risk_level || "MEDIUM",
      weighted_score: item.weighted_score ?? item.score ?? 0,
      notes: item.notes,
    }));
  },

  promoteCandidate: (jobId: string, candidateId: string, notes?: string) =>
    apiFetch(`/jobs/${jobId}/review-queue/${candidateId}/action`, {
      method: "POST",
      body: JSON.stringify({ action: "promote", notes }),
    }),

  rejectCandidate: (jobId: string, candidateId: string, notes?: string) =>
    apiFetch(`/jobs/${jobId}/review-queue/${candidateId}/action`, {
      method: "POST",
      body: JSON.stringify({ action: "confirm_reject", notes }),
    }),

  // Recruiter Profile
  getMe: async (): Promise<UserProfile> => {
    const raw = await apiFetch<any>("/me");
    const primaryTenant = raw.tenants?.[0];
    const profile: UserProfile = {
      ...raw,
      id: raw.user_sub,
      email: raw.email,
      name: raw.username || raw.email?.split("@")[0] || "Recruiter",
      tenant_id: primaryTenant?.tenant_id || "",
      tenant_name: primaryTenant?.name || "Workspace Org",
      role: primaryTenant?.role || "ADMIN",
      tenants: raw.tenants || [],
    };
    if (primaryTenant?.tenant_id) {
      localStorage.setItem(TENANT_KEY, primaryTenant.tenant_id);
    }
    return profile;
  },

  // Public Candidate Portal
  submitApplication: (jobId: string, payload: { name: string; email: string; resume_filename?: string }) =>
    apiFetch<ApplicationInitResponse>(`/jobs/${jobId}/applications`, {
      method: "POST",
      body: JSON.stringify({
        candidate_name: payload.name,
        email: payload.email,
        filename: payload.resume_filename || "resume.pdf",
      }),
    }),

  uploadResumeToS3: async (uploadUrl: string, file: File) => {
    const res = await fetch(uploadUrl, {
      method: "PUT",
      body: file,
      headers: {
        "Content-Type": file.type || "application/pdf",
      },
    });
    if (!res.ok) {
      throw new Error(`Failed to upload resume to S3: ${res.statusText}`);
    }
  },

  getApplicationTrack: async (jobId: string, applicationId: string): Promise<ApplicationTrackStatus> => {
    const res = await apiFetch<any>(`/jobs/${jobId}/applications/${applicationId}/status`);
    return {
      application_id: res.application_id || applicationId,
      job_id: res.job_id || jobId,
      candidate_name: res.candidate_name,
      overall_status: res.status || "PROCESSING",
      steps: {
        s3_upload: res.phase1_status ? "done" : "pending",
        phase1_extraction: res.phase1_status === "COMPLETED" ? "done" : res.phase1_status === "RUNNING" ? "running" : "pending",
        phase2_indexing: res.phase2_status === "INDEXED" || res.phase2_status === "COMPLETED" ? "done" : res.phase2_status === "RUNNING" ? "running" : "pending",
        phase3_4_screening: res.phase3_status === "COMPLETED" || res.phase4_status === "COMPLETED" ? "done" : res.phase3_status === "RUNNING" ? "running" : "pending",
      },
      updated_at: res.updated_at,
    };
  },

  getApplicationFeedback: (jobId: string, applicationId: string, token: string) =>
    apiFetch<CandidateFeedback>(
      `/jobs/${jobId}/applications/${applicationId}/feedback?token=${encodeURIComponent(token)}`
    ),
};
