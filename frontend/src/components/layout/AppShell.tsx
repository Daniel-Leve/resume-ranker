import React, { useState } from 'react';
import { LayoutDashboard, Briefcase, PlaySquare, Settings, Server, UserCheck, GraduationCap, FileText, Sun, Moon, LogOut, User } from 'lucide-react';
import { isMockMode, getApiBaseUrl } from '../../api/client';
import { UserRole } from '../../types';
import { getInitialTheme, applyTheme, ThemeMode } from '../../utils/theme';
import { UserSession } from '../../utils/authStore';

interface AppShellProps {
  children: React.ReactNode;
  activeNav: string;
  userRole: UserRole;
  session?: UserSession | null;
  onNavigate: (page: string) => void;
  onToggleRole: (role: UserRole) => void;
  onOpenConfig: () => void;
  onLogout?: () => void;
}

export function AppShell({ children, activeNav, userRole, session, onNavigate, onToggleRole, onOpenConfig, onLogout }: AppShellProps) {
  const mockEnabled = isMockMode();
  const apiBaseUrl = getApiBaseUrl();
  const [currentTheme, setCurrentTheme] = useState<ThemeMode>(getInitialTheme());

  const toggleTheme = () => {
    const nextTheme: ThemeMode = currentTheme === 'dark' ? 'light' : 'dark';
    setCurrentTheme(nextTheme);
    applyTheme(nextTheme);
  };

  const userName = session?.name || (userRole === 'recruiter' ? 'Acme Recruiter' : 'Student Applicant');

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

              <button
                className={`nav-item ${activeNav === 'settings' ? 'active' : ''}`}
                onClick={() => onNavigate('settings')}
              >
                <Settings size={18} />
                <span>Profile & Saved Resume</span>
              </button>
            </>
          )}
        </nav>

        <div className="sidebar-footer">
          <div style={{ fontWeight: 600, color: 'var(--text-muted)' }}>
            {userName}
          </div>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
            {userRole === 'recruiter' ? 'Tenant: tenant-acme-corp' : 'Session: Candidate Account'}
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
            {/* Quick Theme Toggle Button */}
            <button
              className="btn btn-secondary btn-icon"
              style={{ width: '34px', height: '34px', borderRadius: '8px', padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
              onClick={toggleTheme}
              title={`Switch to ${currentTheme === 'dark' ? 'Light' : 'Dark'} Mode`}
            >
              {currentTheme === 'dark' ? <Sun size={16} style={{ color: '#f59e0b' }} /> : <Moon size={16} style={{ color: 'var(--accent-primary)' }} />}
            </button>

            {/* User Session Profile Pill */}
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.4rem',
                backgroundColor: 'var(--bg-app)',
                padding: '0.35rem 0.75rem',
                borderRadius: '8px',
                border: '1px solid var(--border-color)',
                fontSize: '0.8rem',
                fontWeight: 600,
                color: 'var(--text-main)'
              }}
            >
              <User size={14} style={{ color: 'var(--accent-primary)' }} />
              {userName}
              <span className={`status-badge ${userRole === 'recruiter' ? 'badge-emerald' : 'badge-indigo'}`} style={{ fontSize: '0.68rem', padding: '0.1rem 0.4rem', marginLeft: '0.2rem' }}>
                {userRole === 'recruiter' ? 'Recruiter' : 'Candidate'}
              </span>
            </div>

            {/* Logout / Switch Account Button */}
            {onLogout && (
              <button
                className="btn btn-secondary btn-sm"
                onClick={onLogout}
                title="Switch Account / Logout"
              >
                <LogOut size={14} /> Switch Account
              </button>
            )}

            <div
              className="status-badge badge-emerald"
              title={`API Base URL: ${apiBaseUrl}`}
            >
              <Server size={12} />
              AWS Cloud Connected
            </div>
          </div>
        </header>

        <main className="page-content">
          {children}
        </main>
      </div>
    </div>
  );
}
