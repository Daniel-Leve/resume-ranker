import React, { useState } from 'react';
import { Plus, Search, Filter, Briefcase, ArrowUpRight } from 'lucide-react';
import { Job } from '../types';

interface JobsPageProps {
  jobs: Job[];
  onOpenJobWorkspace: (job: Job) => void;
  onOpenCreateJob: () => void;
}

export function JobsPage({ jobs, onOpenJobWorkspace, onOpenCreateJob }: JobsPageProps) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const filteredJobs = jobs.filter(j => {
    const matchesSearch = j.title.toLowerCase().includes(search.toLowerCase()) ||
                          (j.department || '').toLowerCase().includes(search.toLowerCase());
    const matchesStatus = statusFilter === 'ALL' || j.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Job Requisitions</h1>
          <div className="page-subtitle">Manage open job postings and candidate pipelines</div>
        </div>

        <button className="btn btn-primary" onClick={onOpenCreateJob}>
          <Plus size={16} />
          Create Job Requisition
        </button>
      </div>

      {/* Search & Filter Bar */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem' }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <Search size={16} style={{ position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
          <input
            type="text"
            className="form-input"
            style={{ paddingLeft: '2.5rem' }}
            placeholder="Search job requisitions by title or department..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <select
          className="form-select"
          style={{ width: '180px' }}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="ALL">All Statuses</option>
          <option value="OPEN">Open</option>
          <option value="CLOSED">Closed</option>
        </select>
      </div>

      {/* Jobs Table */}
      <div className="table-wrapper">
        <table className="ui-table">
          <thead>
            <tr>
              <th>Job Title</th>
              <th>Department</th>
              <th>Location</th>
              <th>Candidates</th>
              <th>Status</th>
              <th>Created Date</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {filteredJobs.length > 0 ? (
              filteredJobs.map((job) => (
                <tr key={job.job_id}>
                  <td>
                    <div style={{ fontWeight: 700, color: 'var(--text-main)' }}>{job.title}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                      ID: {job.job_id}
                    </div>
                  </td>
                  <td>{job.department || 'Engineering'}</td>
                  <td>{job.location || 'Remote / Hybrid'}</td>
                  <td>
                    <span className="status-badge badge-indigo">
                      {job.application_count || 0} candidates
                    </span>
                  </td>
                  <td>
                    <span className={`status-badge ${job.status === 'OPEN' ? 'badge-emerald' : 'badge-neutral'}`}>
                      {job.status}
                    </span>
                  </td>
                  <td>{new Date(job.created_at).toLocaleDateString()}</td>
                  <td>
                    <button className="btn btn-secondary btn-sm" onClick={() => onOpenJobWorkspace(job)}>
                      Open Workspace <ArrowUpRight size={14} />
                    </button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '3rem' }}>
                  <div className="empty-title">No job requisitions found</div>
                  <div className="empty-desc">Create a new job requisition to start receiving and screening candidate applications.</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
