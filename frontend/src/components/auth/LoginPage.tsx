import React, { useState } from 'react';
import { Briefcase, GraduationCap, ArrowRight, Lock, Mail, User } from 'lucide-react';
import { UserSession, saveSession, registerUserAccount, findUserAccount } from '../../utils/authStore';

interface LoginPageProps {
  onLogin: (session: UserSession) => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [role, setRole] = useState<'recruiter' | 'candidate'>('recruiter');

  // Form Fields
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg('');

    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail) {
      setErrorMsg('Please enter a valid email address.');
      return;
    }

    if (mode === 'register') {
      const trimmedName = name.trim();
      if (!trimmedName) {
        setErrorMsg('Please enter your full name.');
        return;
      }

      const account = registerUserAccount({
        name: trimmedName,
        email: trimmedEmail,
        password: password.trim(),
        role: role
      });

      const session: UserSession = {
        name: account.name,
        email: account.email,
        role: account.role,
        candidateId: account.id,
        isAuthenticated: true
      };

      saveSession(session);
      onLogin(session);
    } else {
      // Login Mode
      let account = findUserAccount(trimmedEmail, role);

      // If user is logging in for the first time, auto-register them cleanly
      if (!account) {
        const defaultName = trimmedEmail.split('@')[0] ? trimmedEmail.split('@')[0] : (role === 'recruiter' ? 'Recruiter User' : 'Candidate User');
        account = registerUserAccount({
          name: defaultName,
          email: trimmedEmail,
          password: password.trim(),
          role: role
        });
      }

      const session: UserSession = {
        name: account.name,
        email: account.email,
        role: account.role,
        candidateId: account.id,
        isAuthenticated: true
      };

      saveSession(session);
      onLogin(session);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'var(--bg-app)',
        padding: '1.5rem',
        background: 'radial-gradient(circle at 50% 20%, rgba(99, 102, 241, 0.12), transparent 70%), var(--bg-app)'
      }}
    >
      <div
        className="card"
        style={{
          width: '100%',
          maxWidth: '440px',
          padding: '2.25rem',
          borderRadius: '16px',
          boxShadow: '0 20px 40px rgba(0, 0, 0, 0.25)',
          border: '1px solid var(--border-strong)',
          backdropFilter: 'blur(20px)'
        }}
      >
        {/* Brand Header */}
        <div style={{ textAlign: 'center', marginBottom: '1.75rem' }}>
          <div
            style={{
              width: '48px',
              height: '48px',
              borderRadius: '12px',
              background: 'linear-gradient(135deg, var(--accent-primary), #4f46e5)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#ffffff',
              fontWeight: 800,
              fontSize: '1.25rem',
              marginBottom: '0.75rem',
              boxShadow: '0 8px 16px rgba(99, 102, 241, 0.3)'
            }}
          >
            RR
          </div>
          <h1 style={{ fontSize: '1.45rem', fontWeight: 800, color: 'var(--text-main)' }}>Resume Ranker</h1>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
            {mode === 'login' ? 'Sign in to access your workspace' : 'Create your new workspace account'}
          </p>
        </div>

        {/* Role Selector */}
        <div style={{ marginBottom: '1.5rem' }}>
          <label className="form-label" style={{ fontSize: '0.78rem', marginBottom: '0.4rem' }}>Select Role</label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <button
              type="button"
              onClick={() => setRole('recruiter')}
              style={{
                padding: '0.65rem 0.85rem',
                borderRadius: '8px',
                border: role === 'recruiter' ? '2px solid var(--accent-primary)' : '1px solid var(--border-color)',
                backgroundColor: role === 'recruiter' ? 'var(--bg-card)' : 'var(--bg-app)',
                color: 'var(--text-main)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.5rem',
                fontSize: '0.82rem',
                fontWeight: 600
              }}
            >
              <Briefcase size={15} style={{ color: role === 'recruiter' ? 'var(--accent-primary)' : 'var(--text-muted)' }} />
              Recruiter
            </button>

            <button
              type="button"
              onClick={() => setRole('candidate')}
              style={{
                padding: '0.65rem 0.85rem',
                borderRadius: '8px',
                border: role === 'candidate' ? '2px solid var(--accent-primary)' : '1px solid var(--border-color)',
                backgroundColor: role === 'candidate' ? 'var(--bg-card)' : 'var(--bg-app)',
                color: 'var(--text-main)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.5rem',
                fontSize: '0.82rem',
                fontWeight: 600
              }}
            >
              <GraduationCap size={15} style={{ color: role === 'candidate' ? 'var(--accent-emerald)' : 'var(--text-muted)' }} />
              Candidate
            </button>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {mode === 'register' && (
            <div className="form-group">
              <label className="form-label">Full Name</label>
              <div style={{ position: 'relative' }}>
                <User size={16} style={{ position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                <input
                  type="text"
                  className="form-input"
                  style={{ paddingLeft: '2.4rem' }}
                  placeholder={role === 'recruiter' ? 'e.g. Acme Recruiter' : 'e.g. Jane Doe'}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </div>
            </div>
          )}

          <div className="form-group">
            <label className="form-label">Email Address</label>
            <div style={{ position: 'relative' }}>
              <Mail size={16} style={{ position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                type="email"
                className="form-input"
                style={{ paddingLeft: '2.4rem' }}
                placeholder={role === 'recruiter' ? 'recruiter@company.com' : 'candidate@email.com'}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Password</label>
            <div style={{ position: 'relative' }}>
              <Lock size={16} style={{ position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                type="password"
                className="form-input"
                style={{ paddingLeft: '2.4rem' }}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>

          {errorMsg && (
            <div className="status-badge badge-rose" style={{ padding: '0.5rem', justifyContent: 'center', fontSize: '0.78rem' }}>
              {errorMsg}
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%', padding: '0.75rem', justifyContent: 'center', fontSize: '0.88rem', marginTop: '0.25rem' }}
          >
            {mode === 'login' ? 'Sign In to Workspace' : 'Create Account & Continue'} <ArrowRight size={16} />
          </button>
        </form>

        {/* Text link below button to switch between Login and Register */}
        <div style={{ textAlign: 'center', marginTop: '1.25rem', fontSize: '0.82rem', color: 'var(--text-muted)' }}>
          {mode === 'login' ? (
            <>
              Don't have an account?{' '}
              <button
                type="button"
                style={{ background: 'none', border: 'none', color: 'var(--accent-primary)', fontWeight: 600, cursor: 'pointer', padding: 0 }}
                onClick={() => {
                  setMode('register');
                  setErrorMsg('');
                }}
              >
                Create Account
              </button>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <button
                type="button"
                style={{ background: 'none', border: 'none', color: 'var(--accent-primary)', fontWeight: 600, cursor: 'pointer', padding: 0 }}
                onClick={() => {
                  setMode('login');
                  setErrorMsg('');
                }}
              >
                Sign In
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
