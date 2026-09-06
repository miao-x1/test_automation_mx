import { fetchWorkspace } from '@/services/workspace';

const KEY = 'current_project_id';
const NAME_KEY = 'current_project_name';
export const PROJECT_CHANGED = 'project-changed';

export function getCurrentProjectId(): number | null {
  const raw = sessionStorage.getItem(KEY);
  if (!raw) return null;
  const id = Number(raw);
  return Number.isFinite(id) && id > 0 ? id : null;
}

export function getCurrentProjectName(): string {
  return sessionStorage.getItem(NAME_KEY) || '';
}

export function setCurrentProjectId(id: number, name?: string) {
  sessionStorage.setItem(KEY, String(id));
  if (name) sessionStorage.setItem(NAME_KEY, name);
  window.dispatchEvent(new CustomEvent(PROJECT_CHANGED, { detail: { id, name: name || getCurrentProjectName() } }));
}

export function clearCurrentProjectId() {
  sessionStorage.removeItem(KEY);
  sessionStorage.removeItem(NAME_KEY);
  window.dispatchEvent(new CustomEvent(PROJECT_CHANGED, { detail: null }));
}

export async function resolveProjectId(): Promise<number | null> {
  const current = getCurrentProjectId();
  if (current) return current;
  const data = await fetchWorkspace();
  const next = data?.default_project_id || data?.projects?.[0]?.id;
  if (next) setCurrentProjectId(next);
  return next || null;
}
