import React, { useState, useEffect } from 'react';
import { Server, Sun, Moon, Sparkles, FileText, Upload, Trash2, CheckCircle2, User } from 'lucide-react';
import { getApiBaseUrl, isMockMode } from '../api/client';
import { getInitialTheme, applyTheme, ThemeMode } from '../utils/theme';
import { UserSession } from '../utils/authStore';
import { getSavedCandidateResume, saveCandidateDefaultResume, removeCandidateDefaultResume, SavedCandidateResume, fileToBase64 } from '../utils/studentStore';

interface SettingsPageProps {
  onOpenConfig: () => void;
  session?: UserSession | null;
}

export function SettingsPage({ onOpenConfig, session }: SettingsPageProps) {
  const currentUrl = getApiBaseUrl();
  const mock = isMockMode();
  const [themeMode, setThemeMode] = useState<ThemeMode>(getInitialTheme());
  const [savedResume, setSavedResume] = useState<SavedCandidateResume | null>(null);
  const [uploadSuccessMsg, setUploadSuccessMsg] = useState('');

  const candidateKey = session?.email || session?.candidateId || '';

  useEffect(() => {
    if (candidateKey) {
      setSavedResume(getSavedCandidateResume(candidateKey));
    }
  }, [candidateKey]);

  const handleThemeChange = (mode: ThemeMode) => {
    setThemeMode(mode);
    applyTheme(mode);
  };

  const handleResumeFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0] && candidateKey) {
      const file = e.target.files[0];
      try {
        const base64Data = await fileToBase64(file);
        const record: SavedCandidateResume = {
          fileName: file.name,
          fileSize: file.size,
          base64Data,
          savedAt: new Date().toISOString()
        };
        saveCandidateDefaultResume(candidateKey, record);
        setSavedResume(record);
        setUploadSuccessMsg('Default profile resume saved! One-click apply enabled.');
        setTimeout(() => setUploadSuccessMsg(''), 3000);
      } catch (err) {
        console.error('Failed to encode PDF file', err);
      }
    }
  };

  const handleRemoveSavedResume = () => {
    if (candidateKey && window.confirm('Are you sure you want to remove your saved default resume?')) {
      removeCandidateDefaultResume(candidateKey);
      setSavedResume(null);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', maxWidth: '680px' }}>
      <div className="page-header">
        <div>
          <h1 className="page-title">{session?.role === 'candidate' ? 'Candidate Profile & Settings' : 'System Settings'}</h1>
          <div className="page-subtitle">Configure workspace appearance, default resume attachments, and cloud connections</div>
        </div>
      </div>

      {/* Candidate Default Resume Card */}
      {session?.role === 'candidate' && (
        <div className="card">
          <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={18} style={{ color: 'var(--accent-primary)' }} />
            Saved Profile Resume
          </h3>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
            Attach your default PDF resume here to enable 1-click job applications across all open roles.
          </p>

          {savedResume ? (
            <div style={{ backgroundColor: 'var(--bg-app)', padding: '1rem', borderRadius: '10px', border: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <div style={{ padding: '0.5rem', borderRadius: '8px', backgroundColor: 'rgba(16, 185, 129, 0.1)', color: 'var(--accent-emerald)' }}>
                  <FileText size={24} />
                </div>
                <div>
                  <div style={{ fontWeight: 700, color: 'var(--text-main)', fontSize: '0.9rem' }}>{savedResume.fileName}</div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>
                    Size: {(savedResume.fileSize / 1024).toFixed(1)} KB &bull; Saved: {new Date(savedResume.savedAt).toLocaleDateString()}
                  </div>
                </div>
              </div>

              <div style={{ display: 'flex', gap: '0.5rem', position: 'relative' }}>
                <label className="btn btn-secondary btn-sm" style={{ cursor: 'pointer' }}>
                  <Upload size={14} /> Replace PDF
                  <input type="file" accept=".pdf,application/pdf" onChange={handleResumeFileSelect} style={{ display: 'none' }} />
                </label>
                <button className="btn btn-secondary btn-sm btn-icon" style={{ color: 'var(--accent-rose)' }} onClick={handleRemoveSavedResume} title="Remove saved resume">
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ) : (
            <div style={{ border: '2px dashed var(--border-strong)', borderRadius: '10px', padding: '1.5rem', textAlign: 'center', backgroundColor: 'var(--bg-app)', position: 'relative' }}>
              <input
                type="file"
                accept=".pdf,application/pdf"
                onChange={handleResumeFileSelect}
                style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}
              />
              <Upload size={28} style={{ color: 'var(--text-muted)', marginBottom: '0.5rem' }} />
              <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>Click to Upload Saved PDF Resume</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Saves resume locally for 1-click application submissions</div>
            </div>
          )}

          {uploadSuccessMsg && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--accent-emerald)', fontSize: '0.82rem', fontWeight: 600, marginTop: '0.75rem' }}>
              <CheckCircle2 size={15} /> {uploadSuccessMsg}
            </div>
          )}
        </div>
      )}

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
          AWS Cloud REST API Connection
        </h3>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', fontSize: '0.875rem' }}>
          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', fontWeight: 600 }}>Active Endpoint URL</div>
            <code style={{ fontSize: '0.85rem', color: 'var(--text-main)', display: 'block', marginTop: '0.2rem' }}>
              {currentUrl}
            </code>
          </div>

          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', fontWeight: 600 }}>Cloud Environment Status</div>
            <div style={{ marginTop: '0.25rem' }}>
              <span className="status-badge badge-emerald">
                Live AWS SAM REST API & S3 Ingestion Connected
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}


