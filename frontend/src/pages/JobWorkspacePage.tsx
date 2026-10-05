import React, { useState } from 'react';
import { Play, RotateCw, Upload, CheckCircle2, Layers, FileText, ChevronRight, ArrowUp, ArrowDown, Minus, Info } from 'lucide-react';
import { Job, CandidateRanking, ScreeningRun, Application } from '../types';
import { CandidateEvidenceDrawer } from '../features/candidates/CandidateEvidenceDrawer';
import { ArchitectureExplainer } from '../features/screening/ArchitectureExplainer';
import { formatCandidateName, formatCandidateId, formatS3Key } from '../utils/formatters';

interface JobWorkspacePageProps {
  job: Job;
  screeningRun: ScreeningRun | null;
  applications?: Application[];
  onTriggerScreening: () => void;
  onRefresh: () => void;
  onOpenUpload: () => void;
  loading: boolean;
}

export function JobWorkspacePage({
  job,
  screeningRun,
  applications = [],
  onTriggerScreening,
  onRefresh,
  onOpenUpload,
  loading
}: JobWorkspacePageProps) {
  const [activeTab, setActiveTab] = useState<'screening' | 'candidates' | 'details' | 'architecture'>('screening');
  const [selectedCandidate, setSelectedCandidate] = useState<CandidateRanking | null>(null);

  const candidates = screeningRun?.candidates || [];
  const runStatus = screeningRun?.status || 'IDLE';

  const renderRankChange = (change: number) => {
    if (change > 0) {
      return (
        <span style={{ color: 'var(--accent-emerald)', fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.15rem' }} title="Change from hybrid retrieval rank after semantic reranking">
          <ArrowUp size={13} /> +{change}
        </span>
      );
    }
    if (change < 0) {
      return (
        <span style={{ color: 'var(--accent-rose)', fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.15rem' }} title="Change from hybrid retrieval rank after semantic reranking">
          <ArrowDown size={13} /> {change}
        </span>
      );
    }
    return (
      <span style={{ color: 'var(--text-dim)', fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.15rem' }} title="Change from hybrid retrieval rank after semantic reranking">
        <Minus size={13} /> 0
      </span>
    );
  };

  return (
    <div>
      {/* Job Workspace Header */}
      <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '1.25rem 1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.2rem' }}>
              <span className="status-badge badge-emerald">{job.status}</span>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                Requisition ID: {job.job_id}
              </span>
            </div>
            <h1 style={{ fontSize: '1.4rem', fontWeight: 700 }}>{job.title}</h1>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              Department: {job.department || 'Engineering'} &bull; Location: {job.location || 'Remote'} &bull; {job.application_count || candidates.length || applications.length || 0} Registered Applicants
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span className={`status-badge ${runStatus === 'COMPLETED' ? 'badge-emerald' : 'badge-amber'}`}>
              <CheckCircle2 size={13} /> Status: {runStatus}
            </span>

            <button className="btn btn-secondary btn-sm" onClick={onRefresh} title="Refresh results">
              <RotateCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>

            <button className="btn btn-secondary" onClick={onOpenUpload}>
              <Upload size={14} />
              Add Candidates
            </button>

            <button
              className="btn btn-primary"
              onClick={onTriggerScreening}
              disabled={loading || runStatus === 'RUNNING' || runStatus === 'RUNNING_PHASE2' || runStatus === 'RUNNING_PHASE3'}
            >
              <Play size={14} />
              {runStatus.startsWith('RUNNING') ? 'AI Screening Active...' : 'Run AI Screening'}
            </button>
          </div>
        </div>
      </div>

      {/* Navigation Tabs inside Job Workspace */}
      <div className="tab-bar">
        <button
          className={`tab-btn ${activeTab === 'screening' ? 'active' : ''}`}
          onClick={() => setActiveTab('screening')}
        >
          Screening Results ({candidates.length})
        </button>

        <button
          className={`tab-btn ${activeTab === 'candidates' ? 'active' : ''}`}
          onClick={() => setActiveTab('candidates')}
        >
          Registered Candidates ({applications.length || candidates.length || job.application_count || 0})
        </button>

        <button
          className={`tab-btn ${activeTab === 'details' ? 'active' : ''}`}
          onClick={() => setActiveTab('details')}
        >
          Requisition Details
        </button>

        <button
          className={`tab-btn ${activeTab === 'architecture' ? 'active' : ''}`}
          onClick={() => setActiveTab('architecture')}
        >
          Pipeline Architecture
        </button>
      </div>

      {/* Tab 1: Screening Results Table (Visual Centerpiece) */}
      {activeTab === 'screening' && (
        <div>
          {candidates.length > 0 ? (
            <div className="table-wrapper">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Candidate</th>
                    <th>Final Match Score</th>
                    <th>Matched Sections</th>
                    <th title="Change from hybrid retrieval rank after semantic reranking">
                      Rank Shift <Info size={12} style={{ display: 'inline' }} />
                    </th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c, idx) => {
                    const rank = c.rerank_rank || (idx + 1);
                    const scorePct = (c.rerank_score * 100).toFixed(1);
                    const displayName = formatCandidateName(c.candidate_name, c.candidate_id, idx, c.document_chunks);
                    const displayId = formatCandidateId(c.candidate_id);
                    const matched = c.phase2?.matched_chunks || [];

                    return (
                      <tr key={c.candidate_id || idx}>
                        <td>
                          <span className={rank === 1 ? "status-badge badge-emerald" : "status-badge badge-indigo"}>
                            #{rank}
                          </span>
                        </td>
                        <td>
                          <div style={{ fontWeight: 700, color: 'var(--text-main)' }}>{displayName}</div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }} title={c.candidate_id}>
                            ID: {displayId}
                          </div>
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                            <strong style={{ color: 'var(--accent-emerald)', fontFamily: 'var(--font-mono)', fontSize: '0.9rem' }}>
                              {scorePct}%
                            </strong>
                            <div className="progress-bar" style={{ width: '100px' }}>
                              <div className="progress-fill emerald" style={{ width: `${Math.min(100, Math.max(5, c.rerank_score * 100))}%` }} />
                            </div>
                          </div>
                        </td>
                        <td>
                          {matched.length > 0 ? (
                            <div style={{ display: 'flex', gap: '0.3rem', flexWrap: 'wrap' }}>
                              {matched.map((mc, mIdx) => (
                                <span key={mIdx} className="status-badge badge-neutral" style={{ fontSize: '0.7rem' }}>
                                  {mc.section}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Full document</span>
                          )}
                        </td>
                        <td>{renderRankChange(c.rank_change || 0)}</td>
                        <td>
                          <button className="btn btn-secondary btn-sm" onClick={() => setSelectedCandidate(c)}>
                            Inspect Evidence <ChevronRight size={14} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state">
              <Layers size={36} style={{ color: 'var(--text-dim)', margin: '0 auto' }} />
              <div className="empty-title">No candidates have been screened for this job yet</div>
              <div className="empty-desc">Add candidate PDF resumes to register applications, then click "Run AI Screening" to generate semantic candidate rankings.</div>
              <div style={{ marginTop: '1.25rem', display: 'flex', justifyContent: 'center', gap: '0.75rem' }}>
                <button className="btn btn-secondary" onClick={onOpenUpload}>
                  Add Candidates
                </button>
                <button className="btn btn-primary" onClick={onTriggerScreening}>
                  Run AI Screening
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Registered Candidates Tab */}
      {activeTab === 'candidates' && (
        <div className="table-wrapper">
          <table className="ui-table">
            <thead>
              <tr>
                <th>Candidate Name</th>
                <th>Candidate ID</th>
                <th>Status</th>
                <th>S3 Resume Storage</th>
                <th>Registered Date</th>
              </tr>
            </thead>
            <tbody>
              {applications.length > 0 ? (
                applications.map((app, idx) => (
                  <tr key={app.application_id}>
                    <td>
                      <div style={{ fontWeight: 700 }}>{formatCandidateName(app.candidate_name, app.application_id, idx)}</div>
                    </td>
                    <td>
                      <code style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }} title={app.application_id}>
                        {formatCandidateId(app.application_id)}
                      </code>
                    </td>
                    <td>
                      <span className={`status-badge ${app.status === 'INDEXED' ? 'badge-emerald' : 'badge-indigo'}`}>
                        {app.status || 'PENDING_UPLOAD'}
                      </span>
                    </td>
                    <td>
                      <code style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }} title={app.s3_resume_key}>
                        {formatS3Key(app.s3_resume_key)}
                      </code>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        {app.created_at ? new Date(app.created_at).toLocaleDateString() : 'Active'}
                      </span>
                    </td>
                  </tr>
                ))
              ) : candidates.length > 0 ? (
                candidates.map((c, idx) => (
                  <tr key={c.candidate_id}>
                    <td>
                      <div style={{ fontWeight: 700 }}>{formatCandidateName(c.candidate_name, c.candidate_id, idx, c.document_chunks)}</div>
                    </td>
                    <td>
                      <code style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }} title={c.candidate_id}>
                        {formatCandidateId(c.candidate_id)}
                      </code>
                    </td>
                    <td>
                      <span className="status-badge badge-emerald">INDEXED</span>
                    </td>
                    <td>
                      <code style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }} title={c.source_key}>
                        {formatS3Key(c.source_key)}
                      </code>
                    </td>
                    <td>
                      <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Active</span>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '2.5rem' }}>
                    <div className="empty-title">No candidates registered</div>
                    <div className="empty-desc">Click "Add Candidates" to register resume applications for this job.</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 3: Requisition Details */}
      {activeTab === 'details' && (
        <div className="card">
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, marginBottom: '0.75rem' }}>
            Job Description & Specifications
          </h3>
          <div style={{ fontSize: '0.875rem', lineHeight: '1.6', color: 'var(--text-muted)', whiteSpace: 'pre-wrap' }}>
            {job.description}
          </div>
        </div>
      )}

      {/* Tab 4: Architecture Explainer */}
      {activeTab === 'architecture' && (
        <ArchitectureExplainer />
      )}

      {/* Candidate Evidence Drawer */}
      <CandidateEvidenceDrawer
        candidate={selectedCandidate}
        onClose={() => setSelectedCandidate(null)}
      />
    </div>
  );
}
