import { SHIFT_TYPES, type PeriodShiftCount, type ShiftType } from './types';

/** Root senses first, then shift types in the order the interface lists them. */
export const SHIFT_ORDER: ShiftType[] = ['root', ...SHIFT_TYPES];

export interface PeriodRow {
  label: string;
  start: number;
  total: number;
  byShift: Partial<Record<ShiftType, number>>;
}

/** One row per period, oldest first; only the shift types that occur, in SHIFT_ORDER. */
export function pivotPeriods(rows: PeriodShiftCount[]) {
  const map = new Map<string, PeriodRow>();
  for (const r of rows) {
    const p = map.get(r.period) ?? { label: r.period, start: r.period_start, total: 0, byShift: {} };
    p.byShift[r.shift] = (p.byShift[r.shift] ?? 0) + r.senses;
    p.total += r.senses;
    map.set(r.period, p);
  }
  const periods = [...map.values()].sort((a, b) => a.start - b.start);
  const shifts = SHIFT_ORDER.filter((s) => periods.some((p) => p.byShift[s]));
  const maxTotal = Math.max(0, ...periods.map((p) => p.total));
  const maxCell = Math.max(0, ...periods.flatMap((p) => Object.values(p.byShift)));
  return { periods, shifts, maxTotal, maxCell };
}

/** Smallest 1, 2 or 5 × 10^k at or above n: the end of a clean axis. */
export function niceCeil(n: number) {
  if (n <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(n));
  return ([1, 2, 5, 10].find((m) => m * p >= n) ?? 10) * p;
}

/** A clean axis from 0 covering max in about four steps: niceAxis(1165) → 0, 500, 1000, 1500. */
export function niceAxis(max: number) {
  const step = niceCeil(max / 4);
  const top = Math.max(step, Math.ceil(max / step) * step);
  return { max: top, ticks: Array.from({ length: top / step + 1 }, (_, i) => i * step) };
}

/** Strength of a heat cell, 0 for empty, else 0.16–0.9 of the foreground ink. */
export const heatLevel = (v: number, max: number) => (v > 0 && max > 0 ? 0.16 + 0.74 * (v / max) : 0);

/** Above this level the cell is light enough that its number needs dark ink. */
export const HEAT_DARK_INK = 0.55;
