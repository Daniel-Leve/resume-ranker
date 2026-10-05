import React, { useState, useEffect } from 'react';
import { Briefcase, FileText, Upload, CheckCircle2, Search, ArrowRight, UserCheck, Clock, Award, Layers, Trash2, Eye, X } from 'lucide-react';
import { Job, StudentApplicationRecord, ScreeningRun } from '../types';
import { getStudentApplications, removeStudentApplication, updateStudentApplicationScores } from '../utils/studentStore';
import { formatCandidateId, formatS3Key, getJobCandidateCount } from '../utils/formatters';
import { decrementJobApplicationCount } from '../api/jobs';

import { UserSession } from '../utils/authStore';

interface CandidatePortalPageProps {
  jobs: Job[];
  screeningRun: ScreeningRun | null;
  onApplyForJob: (job: Job) => void;
  session?: UserSession | null;
  activeNav?: string;
  onNavigate?: (page: string) => void;
}

export function CandidatePortalPage({ jobs, screeningRun, onApplyForJob, session, activeNav, onNavigate }: CandidatePortalPageProps) {
  const [activeTab, setActiveTab] = useState<'jobs' | 'my-applications'>(() => {
    return activeNav === 'candidate-applications' ? 'my-applications' : 'jobs';
  });
  const [searchQuery, setSearchQuery] = useState('');
  const [myApps, setMyApps] = useState<StudentApplicationRecord[]>([]);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [viewingJob, setViewingJob] = useState<Job | null>(null);

  const loadUserApplications = () => {
    const all = getStudentApplications();
    if (session?.role === 'candidate') {
      const sessEmail = session.email?.toLowerCase().trim();
      const sessName = session.name?.toLowerCase().trim();
      setMyApps(all.filter(a =>
        (sessEmail && a.candidate_email?.toLowerCase().trim() === sessEmail) ||
        (sessName && a.candidate_name.toLowerCase().trim() === sessName) ||
        a.application_id === session.candidateId
      ));
    } else {
      setMyApps(all);
    }
  };

  useEffect(() => {
    loadUserApplications();
  }, [session]);

  useEffect(() => {
    if (screeningRun?.candidates && screeningRun.candidates.length > 0) {
      updateStudentApplicationScores(screeningRun.candidates);
      loadUserApplications();
    }
  }, [screeningRun]);

  useEffect(() => {
    if (activeNav === 'candidate-applications') {
      setActiveTab('my-applications');
    } else if (activeNav === 'candidate-portal') {
      setActiveTab('jobs');
    }
  }, [activeNav]);

  const handleRemoveApplication = (app: StudentApplicationRecord) => {
    if (window.confirm(`Are you sure you want to withdraw your application for "${app.job_title}"?`)) {
      removeStudentApplication(app.application_id);
      decrementJobApplicationCount(app.job_id);
      loadUserApplications();
    }
  };

  const filteredJobs = jobs.filter(j =>
    j.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (j.department && j.department.toLowerCase().includes(searchQuery.toLowerCase())) ||
    (j.recruiter_name && j.recruiter_name.toLowerCase().includes(searchQuery.toLowerCase())) ||
    (j.recruiter_email && j.recruiter_email.toLowerCase().includes(searchQuery.toLowerCase())) ||
    (j.description && j.description.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <div>
      {/* Student Banner */}
      <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
              <span className="status-badge badge-indigo">
                <UserCheck size={12} /> Student & Applicant Workspace
              </span>
            </div>
            <h1 style={{ fontSize: '1.4rem', fontWeight: 700 }}>Career Opportunities & Submission Portal</h1>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              Submit your PDF resume for open roles and track your AI screening analysis status.
            </p>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button
              className={`btn ${activeTab === 'jobs' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => {
                setActiveTab('jobs');
                onNavigate?.('candidate-portal');
              }}
            >
              <Briefcase size={14} /> Open Roles ({jobs.length})
            </button>
            <button
              className={`btn ${activeTab === 'my-applications' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => {
                loadUserApplications();
                setActiveTab('my-applications');
                onNavigate?.('candidate-applications');
              }}
            >
              <FileText size={14} /> My Applications ({myApps.length})
            </button>
          </div>
        </div>
      </div>

      {/* Tab 1: Available Opportunities */}
      {activeTab === 'jobs' && (
        <div>
          {/* Search bar */}
          <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem' }}>
            <div className="search-bar" style={{ flex: 1, position: 'relative' }}>
              <Search size={16} style={{ position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-dim)' }} />
              <input
                type="text"
                className="form-input"
                style={{ paddingLeft: '2.5rem', width: '100%' }}
                placeholder="Search open roles by title, department, or keywords..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>

          {/* Job List Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '1.25rem' }}>
            {filteredJobs.map((job) => (
              <div
                key={job.job_id}
                className="card"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  justify: 'space-between',
                  transition: 'border-color 0.2s ease',
                  border: selectedJob?.job_id === job.job_id ? '1px solid var(--accent-primary)' : undefined
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                    <span className="status-badge badge-emerald">Open Requisition</span>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                      ID: {job.job_id.slice(0, 12)}...
                    </span>
                  </div>

                  <h3 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '0.35rem' }}>{job.title}</h3>

                  <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '0.35rem', display: 'flex', alignItems: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
                    <span>Posted by:</span>
                    <strong style={{ color: 'var(--accent-primary)' }}>{job.recruiter_name || 'Acme Hiring Team'}</strong>
                    <span style={{ color: 'var(--text-dim)', fontSize: '0.78rem' }}>({job.recruiter_email || 'recruiter@company.com'})</span>
                  </div>

                  <div style={{ fontSize: '0.78rem', color: 'var(--text-dim)', marginBottom: '0.85rem' }}>
                    Dept: <strong>{job.department || 'Engineering'}</strong> &bull; Location: <strong>{job.location || 'Remote'}</strong>
                  </div>

                </div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '0.85rem', borderTop: '1px solid var(--border-color)', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                    Applicants: {getJobCandidateCount(job, screeningRun)} &bull; Posted: {new Date(job.created_at).toLocaleDateString()}
                  </span>

                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => setViewingJob(job)}
                    >
                      <Eye size={14} /> View Job
                    </button>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => onApplyForJob(job)}
                    >
                      <Upload size={14} /> Apply Now <ArrowRight size={13} />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab 2: My Submitted Applications */}
      {activeTab === 'my-applications' && (
        <div>
          {myApps.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {myApps.map((app) => {
                // Check if screening results contain match data for candidate
                const matchedCandidate = screeningRun?.candidates?.find(
                  c => c.candidate_id.includes(app.application_id) || c.source_key === app.s3_key
                );

                const score = matchedCandidate?.rerank_score
                  ? (matchedCandidate.rerank_score * 100).toFixed(1)
                  : app.match_score
                  ? (app.match_score * 100).toFixed(1)
                  : null;

                const rank = matchedCandidate?.rerank_rank || app.rerank_rank;

                return (
                  <div key={app.application_id} className="card">
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem', marginBottom: '0.75rem' }}>
                      <div>
                        <span className="status-badge badge-emerald" style={{ marginBottom: '0.3rem' }}>
                          <CheckCircle2 size={12} /> Application Submitted
                        </span>
                        <h3 style={{ fontSize: '1.1rem', fontWeight: 700 }}>{app.job_title}</h3>
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                          Applicant Name: <strong>{app.candidate_name}</strong> &bull; Applied on: {new Date(app.applied_at).toLocaleString()}
                        </div>
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                          Shared by Recruiter: <strong style={{ color: 'var(--accent-primary)' }}>{app.recruiter_name || 'Hiring Recruiter'}</strong> (<span style={{ color: 'var(--text-main)' }}>{app.recruiter_email || 'recruiter@company.com'}</span>) &bull; Dept: <span>{app.department || 'Engineering'}</span>
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        {score ? (
                          <div style={{ textAlign: 'right', backgroundColor: 'var(--bg-app)', padding: '0.65rem 1rem', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>AI Match Score</div>
                            <div style={{ fontSize: '1.3rem', fontWeight: 800, color: 'var(--accent-emerald)', fontFamily: 'var(--font-mono)' }}>
                              {score}%
                            </div>
                            {rank && (
                              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                                Candidate Rank: <strong>#{rank}</strong>
                              </div>
                            )}
                          </div>
                        ) : (
                          <div className="status-badge badge-amber">
                            <Clock size={12} /> Ingestion & Indexing Active
                          </div>
                        )}

                        <button
                          className="btn btn-secondary btn-sm btn-icon"
                          style={{ color: 'var(--accent-rose)', borderColor: 'rgba(244, 63, 94, 0.3)' }}
                          onClick={() => handleRemoveApplication(app)}
                          title="Withdraw Application"
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.75rem', fontSize: '0.8rem', backgroundColor: 'var(--bg-app)', padding: '0.75rem', borderRadius: '6px' }}>
                      <div>
                        <span style={{ color: 'var(--text-dim)' }}>Application ID:</span>
                        <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-main)' }}>{formatCandidateId(app.application_id)}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-dim)' }}>S3 Storage Object:</span>
                        <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-main)' }}>{formatS3Key(app.s3_key)}</div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-dim)' }}>OCR Extraction:</span>
                        <div style={{ color: 'var(--accent-emerald)', fontWeight: 600 }}>Amazon Textract Completed</div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="empty-state">
              <FileText size={36} style={{ color: 'var(--text-dim)', margin: '0 auto' }} />
              <div className="empty-title">No applications submitted yet</div>
              <div className="empty-desc">Explore open career roles under "Open Roles" and submit your PDF resume to track your screening feedback.</div>
              <div style={{ marginTop: '1.25rem' }}>
                <button className="btn btn-primary" onClick={() => setActiveTab('jobs')}>
                  Browse Open Opportunities
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* View Job Details Modal */}
      {viewingJob && (
        <div className="modal-overlay" onClick={() => setViewingJob(null)}>
          <div className="modal-box" style={{ maxWidth: '640px', width: '100%' }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
              <div>
                <span className="status-badge badge-emerald" style={{ marginBottom: '0.35rem' }}>Open Requisition</span>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--text-main)' }}>{viewingJob.title}</h2>
              </div>
              <button className="btn btn-secondary btn-sm btn-icon" onClick={() => setViewingJob(null)}>
                <X size={16} />
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', marginBottom: '1.25rem' }}>
              <div style={{ backgroundColor: 'var(--bg-app)', padding: '0.85rem 1rem', borderRadius: '8px', border: '1px solid var(--border-color)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.82rem' }}>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>Hiring Recruiter:</span>
                  <div style={{ fontWeight: 700, color: 'var(--accent-primary)' }}>{viewingJob.recruiter_name || 'Acme Hiring Team'}</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>{viewingJob.recruiter_email || 'recruiter@company.com'}</div>
                </div>

                <div>
                  <span style={{ color: 'var(--text-dim)' }}>Role Details:</span>
                  <div style={{ fontWeight: 700, color: 'var(--text-main)' }}>{viewingJob.department || 'Engineering'}</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>{viewingJob.location || 'Remote'}</div>
                </div>
              </div>

              <div>
                <h4 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-main)', marginBottom: '0.5rem' }}>
                  Full Job Description & Requirements
                </h4>
                <div style={{ backgroundColor: 'var(--bg-app)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border-color)', fontSize: '0.85rem', lineHeight: '1.6', color: 'var(--text-main)', maxHeight: '320px', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
                  {viewingJob.description}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', borderTop: '1px solid var(--border-color)', paddingTop: '0.85rem' }}>
              <button className="btn btn-secondary" onClick={() => setViewingJob(null)}>
                Close
              </button>
              <button
                className="btn btn-primary"
                onClick={() => {
                  const jobToApply = viewingJob;
                  setViewingJob(null);
                  onApplyForJob(jobToApply);
                }}
              >
                <Upload size={14} /> Apply Now <ArrowRight size={13} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
