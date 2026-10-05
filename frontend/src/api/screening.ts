import { apiRequest, isMockMode } from './client';
import { ScreeningRun } from '../types';
import { MOCK_SCREENING_RUN } from '../fixtures/mockData';

export async function triggerScreening(
  jobId: string
): Promise<{ screening_run_id: string; status: string; message?: string }> {
  if (isMockMode()) {
    return {
      screening_run_id: `run-${Date.now()}`,
      status: "QUEUED",
      message: "Screening run queued successfully."
    };
  }

  return apiRequest<{ screening_run_id: string; status: string; message?: string }>(
    `/jobs/${jobId}/screening`,
    { method: "POST" }
  );
}

export async function getScreeningResults(jobId: string): Promise<ScreeningRun> {
  if (isMockMode()) {
    return MOCK_SCREENING_RUN;
  }

  try {
    return await apiRequest<ScreeningRun>(`/jobs/${jobId}/screening-results`);
  } catch (err: any) {
    if (err.status === 404) {
      // No screening run has been executed for this job yet
      return {
        screening_run_id: "",
        tenant_id: "",
        job_id: jobId,
        status: "IDLE",
        candidates: [],
        created_at: new Date().toISOString()
      };
    }
    throw err;
  }
}
