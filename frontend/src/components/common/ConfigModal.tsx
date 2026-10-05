import React, { useState } from 'react';
import { X, Server, Check } from 'lucide-react';
import { getApiBaseUrl, setApiBaseUrl, isMockMode, setMockMode } from '../../api/client';

interface ConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ConfigModal({ isOpen, onClose }: ConfigModalProps) {
  const [url, setUrl] = useState(getApiBaseUrl());
  const [mock, setMock] = useState(isMockMode());
  const [saved, setSaved] = useState(false);

  if (!isOpen) return null;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setApiBaseUrl(url);
    setMockMode(mock);
    setSaved(true);
    setTimeout(() => {
      setSaved(false);
      onClose();
      window.location.reload();
    }, 600);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Server size={18} style={{ color: 'var(--accent-primary)' }} />
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700 }}>API Gateway Settings</h3>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSave}>
          <div className="form-group">
            <label className="form-label">API Base URL (VITE_API_BASE_URL)</label>
            <input
              type="text"
              className="form-input"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://vxbiq8rt27.execute-api.ap-south-1.amazonaws.com/dev"
            />
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
              Configured via AWS SAM template output.
            </div>
          </div>

          <div style={{ padding: '0.85rem', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-color)', borderRadius: '6px', marginBottom: '1rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem' }}>
              <input
                type="checkbox"
                checked={mock}
                onChange={(e) => setMock(e.target.checked)}
                style={{ width: '16px', height: '16px', accentColor: 'var(--accent-primary)' }}
              />
              Enable Offline Mock Development Fixtures
            </label>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem', paddingLeft: '1.6rem' }}>
              Toggle mock mode for offline testing when AWS services are unreachable.
            </div>
          </div>

          {saved && (
            <div className="status-badge badge-emerald" style={{ width: '100%', padding: '0.65rem', justifyContent: 'center', marginBottom: '1rem' }}>
              <Check size={14} /> Settings Saved! Reloading app...
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.25rem' }}>
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary">
              Save & Apply
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
