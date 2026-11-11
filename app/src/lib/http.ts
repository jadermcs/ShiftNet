// The local ShiftNet API (backend/, `shiftnet serve`). In development Vite proxies /api to it
// (vite.config.ts); `shiftnet serve --static app/dist` serves the built app and the API together.

/** One automatic check. error blocks the submission, review sends it to the review queue. */
export type CheckLevel = 'error' | 'review' | 'note' | 'pass';
export interface Check {
  code: string;
  level: CheckLevel;
  message: string;
}

/** Thrown when the automatic checks refuse a submission; carries the failed checks. */
export class ChecksFailed extends Error {
  constructor(message: string, readonly checks: Check[]) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error('Cannot reach the ShiftNet API. Start it with `uv run shiftnet serve` in backend/.');
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const message = (body && typeof body.message === 'string' && body.message) || `${res.status} ${res.statusText}`;
    if (body && Array.isArray(body.checks) && body.checks.length) throw new ChecksFailed(message, body.checks as Check[]);
    if (res.status === 502 || res.status === 504)
      throw new Error('Cannot reach the ShiftNet API. Start it with `uv run shiftnet serve` in backend/.');
    throw new Error(message);
  }
  return body as T;
}

/** GET /api/<path>, with query parameters. */
export function get<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const qs = params ? '?' + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString() : '';
  return request<T>(`/api/${path}${qs}`);
}

/** POST /api/<path> with a JSON body. */
export function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(`/api/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

/** A path segment from user data (a lemma or an id). */
export const seg = (s: string) => encodeURIComponent(s);
