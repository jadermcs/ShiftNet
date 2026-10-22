// View state kept in the URL so every word, sense and timeline state has a stable link.

import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { POS_ORDER, SHIFT_TYPES, type Pos, type ShiftType } from './types';

export interface ViewParams {
  view: 'senses' | 'timeline';
  order: 'asc' | 'desc';
  at: number | null;
  pos: Pos[];
  shift: ShiftType[];
  from: number | null;
  to: number | null;
}

const num = (v: string | null) => (v != null && v !== '' && Number.isFinite(+v) ? Math.trunc(+v) : null);
const list = <T extends string>(v: string | null, allowed: readonly T[]) =>
  (v ?? '').split(',').filter((x): x is T => (allowed as readonly string[]).includes(x));

export function parseParams(sp: URLSearchParams): ViewParams {
  return {
    view: sp.get('view') === 'timeline' ? 'timeline' : 'senses',
    order: sp.get('order') === 'desc' ? 'desc' : 'asc',
    at: num(sp.get('at')),
    pos: list(sp.get('pos'), POS_ORDER),
    shift: list(sp.get('shift'), [...SHIFT_TYPES, 'root'] as const),
    from: num(sp.get('from')),
    to: num(sp.get('to')),
  };
}

const DEFAULTS: Partial<Record<keyof ViewParams, string>> = { view: 'senses', order: 'asc' };

export function toSearch(p: Partial<ViewParams>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) {
    if (v == null || (Array.isArray(v) && !v.length)) continue;
    const s = Array.isArray(v) ? v.join(',') : String(v);
    if (DEFAULTS[k as keyof ViewParams] === s) continue;
    sp.set(k, s);
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export function useViewParams() {
  const [sp, setSp] = useSearchParams();
  const params = useMemo(() => parseParams(sp), [sp]);
  const update = useCallback(
    (patch: Partial<ViewParams>) => setSp(toSearch({ ...parseParams(sp), ...patch }), { replace: true }),
    [sp, setSp],
  );
  return [params, update] as const;
}

export const matchesFilters = (
  p: Pick<ViewParams, 'pos' | 'shift' | 'from' | 'to'>,
  s: { pos: Pos; shift: ShiftType; date_earliest: number },
) =>
  (!p.pos.length || p.pos.includes(s.pos)) &&
  (!p.shift.length || p.shift.includes(s.shift)) &&
  (p.from == null || s.date_earliest >= p.from) &&
  (p.to == null || s.date_earliest <= p.to);

export const hasFilters = (p: ViewParams) => p.pos.length + p.shift.length > 0 || p.from != null || p.to != null;
