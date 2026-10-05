import { StudentApplicationRecord } from '../types';

const STUDENT_APPS_KEY = 'resume_ranker_student_applications';

export function getStudentApplications(): StudentApplicationRecord[] {
  try {
    const raw = localStorage.getItem(STUDENT_APPS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveStudentApplication(record: StudentApplicationRecord): void {
  try {
    const existing = getStudentApplications().filter(a => a.application_id !== record.application_id);
    const updated = [record, ...existing];
    localStorage.setItem(STUDENT_APPS_KEY, JSON.stringify(updated));
  } catch {
    // Ignore storage errors
  }
}

export function removeStudentApplication(applicationId: string): void {
  try {
    const updated = getStudentApplications().filter(a => a.application_id !== applicationId);
    localStorage.setItem(STUDENT_APPS_KEY, JSON.stringify(updated));
  } catch {
    // Ignore storage errors
  }
}

export function removeStudentApplicationsForJob(jobId: string): void {
  try {
    const updated = getStudentApplications().filter(a => a.job_id !== jobId);
    localStorage.setItem(STUDENT_APPS_KEY, JSON.stringify(updated));
  } catch {
    // Ignore storage errors
  }
}

export function updateStudentApplicationScores(candidates: { candidate_id: string; rerank_score: number; rerank_rank: number; source_key?: string }[]): void {
  try {
    const apps = getStudentApplications();
    let updated = false;
    const newApps = apps.map(app => {
      const match = candidates.find(c =>
        c.candidate_id.includes(app.application_id) ||
        (c.source_key && c.source_key === app.s3_key) ||
        (app.application_id && c.candidate_id.includes(app.application_id.slice(0, 8)))
      );
      if (match) {
        updated = true;
        return {
          ...app,
          match_score: match.rerank_score,
          rerank_rank: match.rerank_rank,
          status: 'SCREENED'
        };
      }
      return app;
    });
    if (updated) {
      localStorage.setItem(STUDENT_APPS_KEY, JSON.stringify(newApps));
    }
  } catch {
    // Ignore storage errors
  }
}

export interface SavedCandidateResume {
  fileName: string;
  fileSize: number;
  base64Data?: string;
  savedAt: string;
}

const CANDIDATE_RESUME_PREFIX = 'resume_ranker_saved_resume_';

export function getSavedCandidateResume(emailOrId?: string): SavedCandidateResume | null {
  if (!emailOrId) return null;
  try {
    const raw = localStorage.getItem(`${CANDIDATE_RESUME_PREFIX}${emailOrId.toLowerCase().trim()}`);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveCandidateDefaultResume(emailOrId: string, record: SavedCandidateResume): void {
  if (!emailOrId) return;
  try {
    localStorage.setItem(`${CANDIDATE_RESUME_PREFIX}${emailOrId.toLowerCase().trim()}`, JSON.stringify(record));
  } catch {
    // Ignore storage errors
  }
}

export function removeCandidateDefaultResume(emailOrId: string): void {
  if (!emailOrId) return;
  try {
    localStorage.removeItem(`${CANDIDATE_RESUME_PREFIX}${emailOrId.toLowerCase().trim()}`);
  } catch {
    // Ignore storage errors
  }
}

export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = error => reject(error);
  });
}

export function base64ToFile(base64: string, filename: string, mimeType = 'application/pdf'): File {
  const arr = base64.split(',');
  const mime = arr[0]?.match(/:(.*?);/)?.[1] || mimeType;
  const bstr = atob(arr[1] || arr[0]);
  let n = bstr.length;
  const u8arr = new Uint8Array(n);
  while (n--) {
    u8arr[n] = bstr.charCodeAt(n);
  }
  return new File([u8arr], filename, { type: mime });
}



