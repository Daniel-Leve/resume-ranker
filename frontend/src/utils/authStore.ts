export interface UserAccount {
  id: string;
  name: string;
  email: string;
  password?: string;
  role: 'recruiter' | 'candidate';
  createdAt: string;
}

export interface UserSession {
  email: string;
  name: string;
  role: 'recruiter' | 'candidate';
  candidateId?: string;
  isAuthenticated: boolean;
}

const REGISTERED_USERS_KEY = 'resume_ranker_registered_users';
const SESSION_KEY = 'resume_ranker_user_session';

export function getRegisteredUsers(): UserAccount[] {
  try {
    const raw = localStorage.getItem(REGISTERED_USERS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function registerUserAccount(input: { name: string; email: string; password?: string; role: 'recruiter' | 'candidate' }): UserAccount {
  const existing = getRegisteredUsers();
  const normalizedEmail = input.email.trim().toLowerCase();
  
  const found = existing.find(u => u.email.toLowerCase() === normalizedEmail && u.role === input.role);
  if (found) {
    // Update name/password if provided
    found.name = input.name.trim() || found.name;
    try {
      localStorage.setItem(REGISTERED_USERS_KEY, JSON.stringify(existing));
    } catch {}
    return found;
  }

  const newAccount: UserAccount = {
    id: `usr-${Date.now()}`,
    name: input.name.trim(),
    email: normalizedEmail,
    password: input.password,
    role: input.role,
    createdAt: new Date().toISOString()
  };

  const updated = [newAccount, ...existing];
  try {
    localStorage.setItem(REGISTERED_USERS_KEY, JSON.stringify(updated));
  } catch {
    // Ignore storage errors
  }
  return newAccount;
}

export function findUserAccount(email: string, role: 'recruiter' | 'candidate'): UserAccount | null {
  const users = getRegisteredUsers();
  return users.find(u => u.email.toLowerCase() === email.trim().toLowerCase() && u.role === role) || null;
}

export function getStoredSession(): UserSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && parsed.isAuthenticated && (parsed.role === 'recruiter' || parsed.role === 'candidate')) {
        return parsed;
      }
    }
  } catch {
    // Ignore storage errors
  }
  return null;
}

export function saveSession(session: UserSession): void {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    localStorage.setItem('resume_ranker_user_role', session.role);
  } catch {
    // Ignore storage errors
  }
}

export function clearSession(): void {
  try {
    localStorage.removeItem(SESSION_KEY);
  } catch {
    // Ignore storage errors
  }
}
