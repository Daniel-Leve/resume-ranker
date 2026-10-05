import React from 'react';
import { LayoutDashboard, Briefcase, PlaySquare, Settings, Server, UserCheck, GraduationCap, FileText } from 'lucide-react';
import { isMockMode, getApiBaseUrl } from '../../api/client';
import { UserRole } from '../../types';

interface AppShellProps {
  children: React.ReactNode;
  activeNav: string;
  userRole: UserRole;
  onNavigate: (page: string) => void;
  onToggleRole: (role: UserRole) => void;
  onOpenConfig: () => void;
}

export function AppShell({ children, activeNav, userRole, onNavigate, onToggleRole, onOpenConfig }: AppShellProps) {
  const mockEnabled = isMockMode();
  const apiBaseUrl = getApiBaseUrl();

  return (
    <div className="app-shell">
      {/* Sidebar Navigation */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="brand-icon">RR</div>
          <div>
            <div className="brand-title">Resume Ranker</div>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
              {userRole === 'recruiter' ? 'Talent Acquisition Enterprise' : 'Applicant Career Portal'}
            </div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {userRole === 'recruiter' ? (
            <>
              <button
                className={`nav-item ${activeNav === 'overview' ? 'active' : ''}`}
                onClick={() => onNavigate('overview')}
              >
                <LayoutDashboard size={18} />
                <span>Overview</span>
              </button>

              <button
                className={`nav-item ${activeNav === 'jobs' || activeNav === 'job-workspace' ? 'active' : ''}`}
                onClick={() => onNavigate('jobs')}
              >
                <Briefcase size={18} />
                <span>Jobs Workspace</span>
              </button>

              <button
                className={`nav-item ${activeNav === 'screening-runs' ? 'active' : ''}`}
                onClick={() => onNavigate('screening-runs')}
              >
                <PlaySquare size={18} />
                <span>Screening Runs</span>
              </button>

              <button
                className={`nav-item ${activeNav === 'settings' ? 'active' : ''}`}
                onClick={() => onNavigate('settings')}
              >
                <Settings size={18} />
                <span>Settings</span>
              </button>
            </>
          ) : (
            <>
              <button
                className={`nav-item ${activeNav === 'candidate-portal' ? 'active' : ''}`}
                onClick={() => onNavigate('candidate-portal')}
              >
                <GraduationCap size={18} />
                <span>Open Opportunities</span>
              </button>

              <button
                className={`nav-item ${activeNav === 'candidate-applications' ? 'active' : ''}`}
                onClick={() => onNavigate('candidate-applications')}
              >
                <FileText size={18} />
                <span>My Applications</span>
              </button>
            </>
          )}
        </nav>

        <div className="sidebar-footer">
          <div style={{ fontWeight: 600, color: 'var(--text-muted)' }}>
            {userRole === 'recruiter' ? 'Acme Enterprise Corp' : 'Student Applicant Profile'}
          </div>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
            {userRole === 'recruiter' ? 'Tenant: tenant-acme-corp' : 'Session: Persistent Local'}
          </div>
        </div>
      </aside>

      {/* Main View Area */}
      <div className="main-view">
        <header className="app-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            <span style={{ cursor: 'pointer' }} onClick={() => onNavigate(userRole === 'recruiter' ? 'overview' : 'candidate-portal')}>
              Resume Ranker
            </span>
            <span>/</span>
            <span style={{ color: 'var(--text-main)', fontWeight: 600, textTransform: 'capitalize' }}>
              {userRole === 'candidate' ? 'Candidate Portal' : activeNav === 'job-workspace' ? 'Job Workspace' : activeNav}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
            {/* Role Switcher Toggle */}
            <div style={{ display: 'inline-flex', backgroundColor: 'var(--bg-app)', padding: '0.2rem', borderRadius: '6px', border: '1px solid var(--border-color)' }}>
              <button
                className={`btn btn-sm ${userRole === 'recruiter' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '0.25rem 0.65rem', fontSize: '0.78rem' }}
                onClick={() => onToggleRole('recruiter')}
              >
                <Briefcase size={13} /> Recruiter
              </button>
              <button
                className={`btn btn-sm ${userRole === 'candidate' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '0.25rem 0.65rem', fontSize: '0.78rem' }}
                onClick={() => onToggleRole('candidate')}
              >
                <GraduationCap size={13} /> Candidate / Student
              </button>
            </div>

            <div
              className={`status-badge ${mockEnabled ? 'badge-amber' : 'badge-emerald'}`}
              style={{ cursor: 'pointer' }}
              onClick={onOpenConfig}
              title={`API: ${apiBaseUrl}`}
            >
              <Server size={12} />
              {mockEnabled ? 'Mock Mode' : 'Live AWS API'}
            </div>

            <button className="btn btn-secondary btn-sm" onClick={onOpenConfig}>
              <Settings size={14} />
              <span>API Gateway</span>
            </button>
          </div>
        </header>

        <main className="page-content">
          {children}
        </main>
      </div>
    </div>
  );
}
