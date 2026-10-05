export interface Tenant {
  tenant_id: string;
  name: string;
  created_at?: string;
  status?: string;
}

export interface Job {
  job_id: string;
  tenant_id: string;
  title: string;
  description: string;
  status: 'OPEN' | 'CLOSED' | string;
  created_at: string;
  application_count?: number;
  department?: string;
  location?: string;
  recruiter_email?: string;
  recruiter_name?: string;
}

export interface Application {
  application_id: string;
  job_id: string;
  tenant_id: string;
  candidate_name: string;
  s3_resume_key: string;
  status: 'PENDING_UPLOAD' | 'INDEXED' | 'SCREENED' | string;
  phase1_status?: string;
  phase2_status?: string;
  phase3_status?: string;
  created_at: string;
}

export interface ApplicationRegistrationResponse {
  application_id: string;
  upload_url: string;
  upload_expires_in_seconds: number;
  s3_key: string;
  instructions?: string;
}

export interface MatchedChunk {
  chunk_id: string;
  section: string;
}

export interface Phase2Provenance {
  hybrid_score: number;
  lexical_rank?: number | null;
  vector_rank?: number | null;
  matched_chunks: MatchedChunk[];
}

export interface CandidateRanking {
  candidate_id: string;
  candidate_name?: string;
  rerank_rank: number;
  rerank_score: number;
  rank_change: number;
  phase2: Phase2Provenance;
  source_key: string;
  document_chunks?: string[];
}

export type ScreeningRunStatus =
  | 'QUEUED'
  | 'RUNNING'
  | 'RUNNING_PHASE2'
  | 'RUNNING_PHASE3'
  | 'COMPLETED'
  | 'FAILED'
  | 'SKIPPED'
  | 'IDLE';

export interface ScreeningRun {
  screening_run_id: string;
  tenant_id: string;
  job_id: string;
  status: ScreeningRunStatus;
  phase2_status?: string;
  phase3_status?: string;
  candidates?: CandidateRanking[];
  candidate_count?: number;
  processing_time_sec?: number;
  created_at: string;
  completed_at?: string;
  error?: string;
}

export interface CreateJobInput {
  title: string;
  description: string;
  department?: string;
  location?: string;
  recruiter_email?: string;
  recruiter_name?: string;
}

export type UserRole = 'recruiter' | 'candidate';

export interface StudentApplicationRecord {
  application_id: string;
  job_id: string;
  job_title: string;
  candidate_name: string;
  candidate_email?: string;
  s3_key: string;
  applied_at: string;
  status: 'SUBMITTED' | 'INDEXED' | 'SCREENED' | string;
  match_score?: number;
  rerank_rank?: number;
}
