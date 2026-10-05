export type ThemeMode = 'dark' | 'light';

const THEME_KEY = 'resume_ranker_theme';

export function getInitialTheme(): ThemeMode {
  try {
    const saved = localStorage.getItem(THEME_KEY) as ThemeMode;
    if (saved === 'dark' || saved === 'light') {
      return saved;
    }
  } catch {
    // Ignore storage errors
  }
  return 'light';
}

export function applyTheme(theme: ThemeMode): void {
  try {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Ignore storage errors
  }
}
