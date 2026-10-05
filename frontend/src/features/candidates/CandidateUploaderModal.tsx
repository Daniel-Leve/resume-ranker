import React, { useState } from 'react';
import { X, Upload, FileText, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { createApplication, uploadResumeToS3 } from '../../api/applications';
import { incrementJobApplicationCount } from '../../api/jobs';
import { Job } from '../../types';
import { registerCandidateName } from '../../utils/formatters';
import { saveStudentApplication } from '../../utils/studentStore';

import { UserSession } from '../../utils/authStore';

interface CandidateUploaderModalProps {
  isOpen: boolean;
  onClose: () => void;
  activeJob: Job | null;
  onUploadSuccess: () => void;
  session?: UserSession | null;
}

export function CandidateUploaderModal({
  isOpen,
  onClose,
  activeJob,
  onUploadSuccess,
  session
}: CandidateUploaderModalProps) {
  const [candidateName, setCandidateName] = useState(() => session?.name || '');
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<'idle' | 'presigning' | 'uploading' | 'processing' | 'success' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  if (!isOpen) return null;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selected = e.target.files[0];
      if (selected.type !== 'application/pdf' && !selected.name.endsWith('.pdf')) {
        setErrorMsg('Please select a valid PDF document.');
        return;
      }
      setErrorMsg('');
      setFile(selected);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const finalName = candidateName.trim() || session?.name || 'Candidate';
    if (!finalName) {
      setErrorMsg('Candidate name is required.');
      return;
    }
    if (!file) {
      setErrorMsg('Please select a PDF resume file to upload.');
      return;
    }

    const jobId = activeJob ? activeJob.job_id : '619b93c8-5eac-42b7-aa9d-417a95a9f550';

    try {
      setLoading(true);
      setErrorMsg('');

      // Step 1: Register application & obtain presigned S3 URL
      setStep('presigning');
      const appData = await createApplication(jobId, finalName);

      // Register candidate name in local name registry & student applications
      registerCandidateName(appData.application_id, finalName);
      if (appData.s3_key) registerCandidateName(appData.s3_key, finalName);

      saveStudentApplication({
        application_id: appData.application_id,
        job_id: jobId,
        job_title: activeJob ? activeJob.title : 'General Application',
        candidate_name: finalName,
        candidate_email: session?.email,
        s3_key: appData.s3_key,
        applied_at: new Date().toISOString(),
        status: 'SUBMITTED'
      });

      incrementJobApplicationCount(jobId);

      // Step 2: Upload PDF directly to S3 via presigned URL
      setStep('uploading');
      try {
        await uploadResumeToS3(appData.upload_url, file);
      } catch (s3Err: any) {
        throw new Error(`Application registered (${appData.application_id.slice(0, 8)}...), but S3 resume upload failed: ${s3Err.message || 'CORS or network error. Deploy phase1.yaml S3 CORS configuration.'}`);
      }

      // Step 3: Successfully uploaded
      setStep('processing');
      await new Promise(r => setTimeout(r, 800));

      setStep('success');
      setTimeout(() => {
        setStep('idle');
        setCandidateName('');
        setFile(null);
        setLoading(false);
        onUploadSuccess();
        onClose();
      }, 1500);

    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.message || 'Failed to upload candidate resume.');
      setStep('error');
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={() => !loading && onClose()}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
          <div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700 }}>Add Candidate Resume</h3>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              Requisition: <strong style={{ color: 'var(--text-main)' }}>{activeJob ? activeJob.title : 'General Pipeline'}</strong>
            </div>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={onClose} disabled={loading}>
            <X size={16} />
          </button>
        </div>

        {step === 'success' ? (
          <div style={{ textAlign: 'center', padding: '2rem 1rem' }}>
            <CheckCircle2 size={44} style={{ color: 'var(--accent-emerald)', margin: '0 auto 0.75rem auto' }} />
            <h4 style={{ fontSize: '1.05rem', fontWeight: 700 }}>Resume Registered & Uploaded</h4>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
              Amazon Textract OCR extraction and Voyage AI vector indexing triggered in background.
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label">Candidate Full Name</label>
              <input
                type="text"
                className="form-input"
                placeholder="e.g. John Doe"
                value={candidateName}
                onChange={(e) => setCandidateName(e.target.value)}
                disabled={loading}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label">Resume Document (PDF)</label>
              <div
                style={{
                  border: '2px dashed var(--border-strong)',
                  borderRadius: '8px',
                  padding: '1.5rem',
                  textAlign: 'center',
                  backgroundColor: 'var(--bg-app)',
                  position: 'relative'
                }}
              >
                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={handleFileChange}
                  disabled={loading}
                  style={{
                    position: 'absolute',
                    inset: 0,
                    opacity: 0,
                    cursor: 'pointer'
                  }}
                />
                <Upload size={28} style={{ color: 'var(--text-muted)', marginBottom: '0.5rem' }} />
                {file ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', color: 'var(--accent-emerald)', fontWeight: 600, fontSize: '0.85rem' }}>
                    <FileText size={16} />
                    {file.name} ({(file.size / 1024).toFixed(1)} KB)
                  </div>
                ) : (
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>Click or Drag PDF resume here</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>PDF up to 10MB supported</div>
                  </div>
                )}
              </div>
            </div>

            {errorMsg && (
              <div className="status-badge badge-rose" style={{ width: '100%', padding: '0.65rem', marginBottom: '1rem', justifyContent: 'center' }}>
                <AlertCircle size={14} /> {errorMsg}
              </div>
            )}

            {loading && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
                <Loader2 size={16} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
                {step === 'presigning' && 'Generating presigned S3 URL...'}
                {step === 'uploading' && 'Uploading PDF directly to Amazon S3...'}
                {step === 'processing' && 'Registering indexing worker trigger...'}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.25rem' }}>
              <button type="button" className="btn btn-secondary" onClick={onClose} disabled={loading}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={loading}>
                {loading ? 'Processing...' : 'Upload Resume'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
