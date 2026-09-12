export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

export const THEME_CHANGED = 'platform-theme-changed';
const KEY = 'platform_theme';

export function getThemePreference(): ThemePreference {
  const raw = localStorage.getItem(KEY);
  if (raw === 'light' || raw === 'dark' || raw === 'system') return raw;
  return 'system';
}

export function systemTheme(): ResolvedTheme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function resolveTheme(preference: ThemePreference = getThemePreference()): ResolvedTheme {
  return preference === 'system' ? systemTheme() : preference;
}

export function applyResolvedTheme(resolved: ResolvedTheme) {
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
}

export function setThemePreference(preference: ThemePreference) {
  localStorage.setItem(KEY, preference);
  applyResolvedTheme(resolveTheme(preference));
  window.dispatchEvent(new CustomEvent(THEME_CHANGED, { detail: preference }));
}

export function initTheme() {
  applyResolvedTheme(resolveTheme());
}

export function subscribeTheme(onChange: (preference: ThemePreference, resolved: ResolvedTheme) => void) {
  const emit = () => onChange(getThemePreference(), resolveTheme());
  const onPref = () => emit();
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  window.addEventListener(THEME_CHANGED, onPref);
  media.addEventListener('change', onPref);
  return () => {
    window.removeEventListener(THEME_CHANGED, onPref);
    media.removeEventListener('change', onPref);
  };
}
