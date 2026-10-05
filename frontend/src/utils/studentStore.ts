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

