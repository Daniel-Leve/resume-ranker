import React from 'react';
import { Server, Settings } from 'lucide-react';
import { getApiBaseUrl, isMockMode } from '../api/client';

interface SettingsPageProps {
  onOpenConfig: () => void;
}

export function SettingsPage({ onOpenConfig }: SettingsPageProps) {
  const currentUrl = getApiBaseUrl();
  const mock = isMockMode();

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">System Settings</h1>
          <div className="page-subtitle">Configure backend endpoints, environment stage, and integration modes</div>
        </div>
      </div>

      <div className="card" style={{ maxWidth: '640px' }}>
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
