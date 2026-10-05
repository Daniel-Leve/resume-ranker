import React from 'react';
import { Briefcase, Users, PlaySquare, CheckCircle2, ArrowUpRight, Plus } from 'lucide-react';
import { Job, ScreeningRun } from '../types';

interface OverviewPageProps {
  jobs: Job[];
  screeningRun: ScreeningRun | null;
  onOpenJobWorkspace: (job: Job) => void;
  onOpenCreateJob: () => void;
  onNavigate: (page: string) => void;
}

export function OverviewPage({
  jobs,
  screeningRun,
  onOpenJobWorkspace,
  onOpenCreateJob,
  onNavigate
}: OverviewPageProps) {
  const activeJobsCount = jobs.filter(j => j.status === 'OPEN').length;
  const totalApplicationsCount = jobs.reduce((acc, j) => acc + (j.application_count || 0), 0);
  const candidatesCount = screeningRun?.candidates?.length || 3;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Recruitment Operations Overview</h1>
          <div className="page-subtitle">Real-time AI resume screening and candidate ranking intelligence</div>
        </div>

        <button className="btn btn-primary" onClick={onOpenCreateJob}>
          <Plus size={16} />
          Create Job Requisition
        </button>
      </div>

      {/* Operational Metrics Cards */}
      <div className="card-grid">
        <div className="card">
          <div className="card-label">Active Requisitions</div>
          <div className="card-value">{activeJobsCount}</div>
        </div>

        <div className="card">
          <div className="card-label">Registered Applications</div>
          <div className="card-value">{totalApplicationsCount}</div>
        </div>

        <div className="card">
          <div className="card-label">Screened Candidates</div>
          <div className="card-value" style={{ color: 'var(--accent-emerald)' }}>{candidatesCount}</div>
        </div>

        <div className="card">
          <div className="card-label">AI Reranking Engine</div>
          <div className="card-value" style={{ fontSize: '1.25rem' }}>Voyage rerank-2.5</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: '1.5rem' }}>
        {/* Recent Jobs Requisitions */}
        <div className="card" style={{ padding: 0 }}>
          <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ fontSize: '0.95rem', fontWeight: 700 }}>Active Job Requisitions</h3>
            <button className="btn btn-secondary btn-sm" onClick={() => onNavigate('jobs')}>
              View All Jobs <ArrowUpRight size={14} />
            </button>
          </div>

          <div className="table-wrapper" style={{ border: 'none', borderRadius: 0 }}>
            <table className="ui-table">
              <thead>
                <tr>
                  <th>Job Title</th>
                  <th>Department</th>
                  <th>Candidates</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {jobs.slice(0, 5).map((job) => (
                  <tr key={job.job_id}>
                    <td>
                      <div style={{ fontWeight: 700 }}>{job.title}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                        ID: {job.job_id}
                      </div>
                    </td>
                    <td>{job.department || 'Engineering'}</td>
                    <td>
                      <span className="status-badge badge-indigo">
                        {job.application_count || 0} candidates
                      </span>
                    </td>
                    <td>
                      <span className="status-badge badge-emerald">
                        {job.status}
                      </span>
                    </td>
                    <td>
                      <button className="btn btn-secondary btn-sm" onClick={() => onOpenJobWorkspace(job)}>
                        Open Workspace
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Operational System Status */}
        <div className="card">
          <h3 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '1rem' }}>
            System Pipeline Status
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div style={{ padding: '0.75rem', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-color)', borderRadius: '6px' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>Phase 1 Textract OCR</div>
              <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--accent-emerald)', marginTop: '0.15rem' }}>
                Operational (S3 Async Event)
              </div>
            </div>

            <div style={{ padding: '0.75rem', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-color)', borderRadius: '6px' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>Phase 2 Hybrid Retrieval</div>
              <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#a5b4fc', marginTop: '0.15rem' }}>
                BM25 + Voyage-4-Large Vector RRF
              </div>
            </div>

            <div style={{ padding: '0.75rem', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-color)', borderRadius: '6px' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>Phase 3 Semantic Reranking</div>
              <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--accent-emerald)', marginTop: '0.15rem' }}>
                Voyage rerank-2.5 Active
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
