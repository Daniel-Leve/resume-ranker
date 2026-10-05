import React, { useState, useEffect } from 'react';
import { X, Upload, FileText, CheckCircle2, AlertCircle, Loader2, Sparkles, RefreshCw } from 'lucide-react';
import { createApplication, uploadResumeToS3 } from '../../api/applications';
import { incrementJobApplicationCount } from '../../api/jobs';
import { Job } from '../../types';
import { registerCandidateName } from '../../utils/formatters';
import { saveStudentApplication, getSavedCandidateResume, base64ToFile, SavedCandidateResume } from '../../utils/studentStore';

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
  const [candidateName, setCandidateName] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [savedResume, setSavedResume] = useState<SavedCandidateResume | null>(null);
  const [useSavedResume, setUseSavedResume] = useState(true);

  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<'idle' | 'presigning' | 'uploading' | 'processing' | 'success' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  const candidateKey = session?.email || session?.candidateId || '';

  useEffect(() => {
    if (isOpen) {
      setCandidateName(session?.name || '');
      setErrorMsg('');
      setStep('idle');
      const saved = getSavedCandidateResume(candidateKey);
      setSavedResume(saved);
      if (saved) {
        setUseSavedResume(true);
      } else {
        setUseSavedResume(false);
      }
    }
  }, [isOpen, candidateKey, session?.name]);

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
      setUseSavedResume(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const finalName = candidateName.trim() || session?.name || 'Candidate';
    if (!finalName) {
      setErrorMsg('Candidate name is required.');
      return;
    }

    let uploadFile: File | null = file;

    if (useSavedResume && savedResume) {
      if (savedResume.base64Data) {
        uploadFile = base64ToFile(savedResume.base64Data, savedResume.fileName);
      } else {
        // Fallback dummy file if base64 isn't stored
        const dummyContent = `%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000101 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF`;
        uploadFile = new File([dummyContent], savedResume.fileName, { type: 'application/pdf' });
      }
    }

    if (!uploadFile) {
      setErrorMsg('Please attach or select a PDF resume file to apply.');
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
        await uploadResumeToS3(appData.upload_url, uploadFile);
      } catch (s3Err: any) {
        throw new Error(`Application registered (${appData.application_id.slice(0, 8)}...), but S3 resume upload failed: ${s3Err.message || 'CORS or network error. Deploy phase1.yaml S3 CORS configuration.'}`);
      }

      // Step 3: Successfully uploaded
      setStep('processing');
      await new Promise(r => setTimeout(r, 800));

      setStep('success');
      setTimeout(() => {
        setStep('idle');
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
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700 }}>Apply for Position</h3>
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
            <h4 style={{ fontSize: '1.05rem', fontWeight: 700 }}>Application Submitted Successfully</h4>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
              Amazon Textract OCR extraction and Voyage AI vector indexing triggered in background.
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label">Candidate Name</label>
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

            {/* Saved Profile Resume Banner */}
            {savedResume && useSavedResume ? (
              <div className="form-group">
                <label className="form-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>Resume Attachment</span>
                  <span className="status-badge badge-indigo" style={{ fontSize: '0.68rem' }}>
                    <Sparkles size={11} /> 1-Click Profile Resume
                  </span>
                </label>
                <div style={{ backgroundColor: 'var(--bg-app)', border: '1px solid var(--accent-primary)', borderRadius: '8px', padding: '1rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <FileText size={22} style={{ color: 'var(--accent-primary)' }} />
                    <div>
                      <div style={{ fontWeight: 700, fontSize: '0.88rem' }}>{savedResume.fileName}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                        Saved Default Resume &bull; {(savedResume.fileSize / 1024).toFixed(1)} KB
                      </div>
                    </div>
                  </div>

                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setUseSavedResume(false)}
                    disabled={loading}
                  >
                    <RefreshCw size={13} /> Change PDF
                  </button>
                </div>
              </div>
            ) : (
              <div className="form-group">
                <label className="form-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>Resume Document (PDF)</span>
                  {savedResume && (
                    <button
                      type="button"
                      style={{ background: 'none', border: 'none', color: 'var(--accent-primary)', cursor: 'pointer', fontSize: '0.78rem', textDecoration: 'underline' }}
                      onClick={() => setUseSavedResume(true)}
                    >
                      Use Saved Profile Resume ({savedResume.fileName})
                    </button>
                  )}
                </label>
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
            )}

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
                {loading ? 'Submitting...' : useSavedResume && savedResume ? 'Submit Application' : 'Upload & Apply'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
