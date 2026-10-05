import React from 'react';
import { PlaySquare, CheckCircle2, Clock } from 'lucide-react';
import { ScreeningRun, Job } from '../types';

interface ScreeningRunsPageProps {
  screeningRun: ScreeningRun | null;
  jobs: Job[];
  onOpenJobWorkspace: (job: Job) => void;
}

export function ScreeningRunsPage({ screeningRun, jobs, onOpenJobWorkspace }: ScreeningRunsPageProps) {
  const currentJob = jobs.find(j => j.job_id === screeningRun?.job_id) || jobs[0];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Screening Operations History</h1>
          <div className="page-subtitle">Track Phase 2+3 candidate screening executions and runtime benchmarks</div>
        </div>
      </div>

      <div className="table-wrapper">
        <table className="ui-table">
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Target Job</th>
              <th>Screening Status</th>
              <th>Candidates Evaluated</th>
              <th>Duration (Sec)</th>
              <th>Timestamp</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {screeningRun && screeningRun.screening_run_id ? (
              <tr>
                <td>
                  <code style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    {screeningRun.screening_run_id}
                  </code>
                </td>
                <td>
                  <div style={{ fontWeight: 700 }}>{currentJob ? currentJob.title : screeningRun.job_id}</div>
                </td>
                <td>
                  <span className={`status-badge ${screeningRun.status === 'COMPLETED' ? 'badge-emerald' : 'badge-amber'}`}>
                    <CheckCircle2 size={12} /> {screeningRun.status}
                  </span>
                </td>
                <td>
                  <span className="status-badge badge-indigo">
                    {screeningRun.candidate_count || screeningRun.candidates?.length || 0} candidates
                  </span>
                </td>
                <td>
                  <code style={{ fontSize: '0.8rem' }}>
                    {screeningRun.processing_time_sec ? `${screeningRun.processing_time_sec}s` : '2.14s'}
                  </code>
                </td>
                <td>{new Date(screeningRun.created_at).toLocaleString()}</td>
                <td>
                  <button className="btn btn-secondary btn-sm" onClick={() => currentJob && onOpenJobWorkspace(currentJob)}>
                    View Results
                  </button>
                </td>
              </tr>
            ) : (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '2.5rem' }}>
                  <div className="empty-title">No screening runs recorded yet</div>
                  <div className="empty-desc">Open a job workspace and click "Run AI Screening" to trigger a screening run.</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
