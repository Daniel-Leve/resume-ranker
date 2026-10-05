/**
 * Utility functions to format raw SaaS keys and technical IDs into readable display labels.
 * Includes candidate name registry and resume header text name extraction.
 */

const LOCAL_NAME_REGISTRY_KEY = 'resume_ranker_candidate_names';

function getLocalNameRegistry(): Record<string, string> {
  try {
    const raw = localStorage.getItem(LOCAL_NAME_REGISTRY_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function registerCandidateName(idOrKey: string, name: string): void {
  if (!idOrKey || !name) return;
  try {
    const reg = getLocalNameRegistry();
    reg[idOrKey] = name;
    // Also index by short application UUID if saas key
    if (idOrKey.includes('saas__')) {
      const parts = idOrKey.split('__');
      const uuid = parts[parts.length - 1];
      if (uuid) reg[uuid] = name;
    }
    localStorage.setItem(LOCAL_NAME_REGISTRY_KEY, JSON.stringify(reg));
  } catch {
    // Ignore storage errors
  }
}

export function extractNameFromText(documentChunks?: string[]): string | null {
  if (!documentChunks || documentChunks.length === 0) return null;

  for (const chunk of documentChunks) {
    if (!chunk) continue;
    const lines = chunk.split('\n').map(l => l.trim()).filter(Boolean);
    for (const line of lines) {
      if (line.toLowerCase().startsWith('section:') || line.toLowerCase().startsWith('header:')) continue;
      // Match lines like "Daniel Leve", "Alex Chen", "Dr. Jane H. Smith"
      if (/^(?:[A-Z][a-z]+\.?\s+){1,3}[A-Z][a-z]+$/.test(line)) {
        return line;
      }
    }
  }
  return null;
}

export function formatCandidateName(
  candidateName?: string,
  candidateId?: string,
  fallbackIndex?: number,
  documentChunks?: string[]
): string {
  // 1. Direct candidate_name if valid
  if (candidateName && !candidateName.includes('saas__') && !candidateName.startsWith('extracted/')) {
    return candidateName;
  }

  const reg = getLocalNameRegistry();
  const idStr = candidateId || candidateName || '';

  // 2. Check local name registry by full ID or short UUID
  if (reg[idStr]) return reg[idStr];
  if (idStr.includes('saas__')) {
    const parts = idStr.split('__');
    const uuid = parts[parts.length - 1];
    if (uuid && reg[uuid]) return reg[uuid];
  }

  // 3. Extract candidate name from resume document text chunks if available
  const extractedName = extractNameFromText(documentChunks);
  if (extractedName) return extractedName;

  // 4. Fallback to clean Candidate #N (UUID) tag
  if (idStr.includes('saas__')) {
    const parts = idStr.split('__');
    const appUuid = parts[parts.length - 1];
    const shortId = appUuid ? appUuid.slice(0, 8).toUpperCase() : 'UNKNOWN';
    return fallbackIndex !== undefined ? `Candidate #${fallbackIndex + 1} (${shortId})` : `Candidate (${shortId})`;
  }

  if (idStr) {
    return `Candidate ${idStr.slice(0, 10)}`;
  }

  return fallbackIndex !== undefined ? `Candidate #${fallbackIndex + 1}` : 'Candidate';
}

export function formatCandidateId(candidateId?: string): string {
  if (!candidateId) return 'N/A';
  if (candidateId.includes('saas__')) {
    const parts = candidateId.split('__');
    const appUuid = parts[parts.length - 1];
    return `APP-${appUuid.slice(0, 8).toUpperCase()}`;
  }
  return candidateId.length > 18 ? `${candidateId.slice(0, 18)}...` : candidateId;
}

export function formatS3Key(key?: string): string {
  if (!key) return 'Resume Document';
  if (key.startsWith('extracted/')) {
    const hash = key.replace('extracted/', '').replace('.json', '');
    return `OCR Extracted (${hash.slice(0, 8)})`;
  }
  if (key.startsWith('incoming/')) {
    const parts = key.split('__');
    const appUuid = parts[parts.length - 1] || key;
    return `PDF Resume (${appUuid.slice(0, 8)})`;
  }
  return key.length > 28 ? `${key.slice(0, 28)}...` : key;
}
