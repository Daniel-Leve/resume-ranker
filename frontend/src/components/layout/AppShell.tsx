import React from 'react';
import { LayoutDashboard, Briefcase, PlaySquare, Settings, Database, Server, RefreshCw } from 'lucide-react';
import { isMockMode, getApiBaseUrl } from '../../api/client';

interface AppShellProps {
  children: React.ReactNode;
  activeNav: string;
  onNavigate: (page: string) => void;
  onOpenConfig: () => void;
}

export function AppShell({ children, activeNav, onNavigate, onOpenConfig }: AppShellProps) {
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
            <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>Talent Acquisition AI</div>
          </div>
        </div>

        <nav className="sidebar-nav">
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
        </nav>

        <div className="sidebar-footer">
          <div style={{ fontWeight: 600, color: 'var(--text-muted)' }}>Acme Enterprise Corp</div>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>Tenant ID: tenant-acme-corp</div>
        </div>
      </aside>

      {/* Main View Area */}
      <div className="main-view">
        <header className="app-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            <span style={{ cursor: 'pointer' }} onClick={() => onNavigate('overview')}>Resume Ranker</span>
            <span>/</span>
            <span style={{ color: 'var(--text-main)', fontWeight: 600, textTransform: 'capitalize' }}>
              {activeNav === 'job-workspace' ? 'Job Workspace' : activeNav}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
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
