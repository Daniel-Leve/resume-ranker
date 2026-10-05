import React, { useState } from 'react';
import { Server, Sun, Moon, Sparkles } from 'lucide-react';
import { getApiBaseUrl, isMockMode } from '../api/client';
import { getInitialTheme, applyTheme, ThemeMode } from '../utils/theme';

interface SettingsPageProps {
  onOpenConfig: () => void;
}

export function SettingsPage({ onOpenConfig }: SettingsPageProps) {
  const currentUrl = getApiBaseUrl();
  const mock = isMockMode();
  const [themeMode, setThemeMode] = useState<ThemeMode>(getInitialTheme());

  const handleThemeChange = (mode: ThemeMode) => {
    setThemeMode(mode);
    applyTheme(mode);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', maxWidth: '680px' }}>
      <div className="page-header">
        <div>
          <h1 className="page-title">System Settings</h1>
          <div className="page-subtitle">Configure UI appearance, backend endpoints, and integration modes</div>
        </div>
      </div>

      {/* Theme Card */}
      <div className="card">
        <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Sparkles size={18} style={{ color: 'var(--accent-primary)' }} />
          Appearance & Theme Mode
        </h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '1.25rem' }}>
          Select your preferred workspace aesthetic. Built with precision Apple-grade design standards.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
          <button
            type="button"
            onClick={() => handleThemeChange('dark')}
            className={`card ${themeMode === 'dark' ? 'selected-role' : ''}`}
            style={{
              padding: '1rem',
              cursor: 'pointer',
              border: themeMode === 'dark' ? '2px solid var(--accent-primary)' : '1px solid var(--border-color)',
              background: 'var(--bg-card)',
              textAlign: 'left',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem',
              borderRadius: '12px'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600, color: 'var(--text-main)' }}>
                <Moon size={18} style={{ color: 'var(--accent-primary)' }} />
                Dark Mode (Obsidian)
              </div>
              {themeMode === 'dark' && <span className="badge badge-emerald" style={{ fontSize: '0.7rem' }}>Active</span>}
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: 0 }}>
              Deep translucent glassmorphism with high contrast for low-light environments.
            </p>
          </button>

          <button
            type="button"
            onClick={() => handleThemeChange('light')}
            className={`card ${themeMode === 'light' ? 'selected-role' : ''}`}
            style={{
              padding: '1rem',
              cursor: 'pointer',
              border: themeMode === 'light' ? '2px solid var(--accent-primary)' : '1px solid var(--border-color)',
              background: 'var(--bg-card)',
              textAlign: 'left',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem',
              borderRadius: '12px'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600, color: 'var(--text-main)' }}>
                <Sun size={18} style={{ color: '#f59e0b' }} />
                Light Mode (Alabaster)
              </div>
              {themeMode === 'light' && <span className="badge badge-emerald" style={{ fontSize: '0.7rem' }}>Active</span>}
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: 0 }}>
              Clean, bright canvas with crisp typography and subtle drop shadows.
            </p>
          </button>
        </div>
      </div>

      {/* API Connection Card */}
      <div className="card">
        <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Server size={18} style={{ color: 'var(--accent-primary)' }} />
          API Gateway Connection
        </h3>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', fontSize: '0.875rem' }}>
          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', fontWeight: 600 }}>Active Base URL</div>
            <code style={{ fontSize: '0.85rem', color: 'var(--text-main)', display: 'block', marginTop: '0.2rem' }}>
              {currentUrl}
            </code>
          </div>

          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', fontWeight: 600 }}>Execution Mode</div>
            <div style={{ marginTop: '0.2rem' }}>
              <span className={`status-badge ${mock ? 'badge-amber' : 'badge-emerald'}`}>
                {mock ? 'Offline Mock Fixtures Enabled' : 'Live AWS SAM REST API Connected'}
              </span>
            </div>
          </div>

          <div style={{ paddingTop: '0.75rem', borderTop: '1px solid var(--border-color)' }}>
            <button className="btn btn-primary" onClick={onOpenConfig}>
              Configure Endpoint / Toggle Mock Mode
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

