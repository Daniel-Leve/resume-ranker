import { apiRequest, isMockMode } from './client';
import { ApplicationRegistrationResponse } from '../types';

export async function createApplication(
  jobId: string,
  candidateName: string
): Promise<ApplicationRegistrationResponse> {
  if (isMockMode()) {
    return {
      application_id: `app-${Date.now()}`,
      upload_url: "",
      upload_expires_in_seconds: 900,
      s3_key: `incoming/${candidateName.toLowerCase().replace(/\s+/g, '-')}.pdf`,
      instructions: "PUT your PDF to the upload_url with Content-Type: application/pdf"
    };
  }

  return apiRequest<ApplicationRegistrationResponse>(`/jobs/${jobId}/applications`, {
    method: "POST",
    body: JSON.stringify({ candidate_name: candidateName }),
  });
}

export async function uploadResumeToS3(
  uploadUrl: string,
  file: File
): Promise<{ success: boolean; simulated?: boolean }> {
  if (!uploadUrl || isMockMode()) {
    // Simulate upload delay for offline mock testing
    await new Promise(r => setTimeout(r, 1000));
    return { success: true, simulated: true };
  }

  const res = await fetch(uploadUrl, {
    method: "PUT",
    headers: {
      "Content-Type": "application/pdf"
    },
    body: file
  });

  if (!res.ok) {
    throw new Error(`S3 upload failed with HTTP status ${res.status}: ${res.statusText}`);
  }

  return { success: true };
}
