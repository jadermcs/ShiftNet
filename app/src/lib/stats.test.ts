import { describe, expect, it } from 'vitest';
import { heatLevel, niceAxis, niceCeil, pivotPeriods } from './stats';

describe('pivotPeriods', () => {
  it('groups by period, oldest first, keeping only shift types that occur', () => {
    const { periods, shifts, maxTotal, maxCell } = pivotPeriods([
      { period: '1990s', period_start: 1990, shift: 'metaphor', senses: 3 },
      { period: 'Old English', period_start: 800, shift: 'root', senses: 2 },
      { period: '1990s', period_start: 1990, shift: 'metonymy', senses: 1 },
    ]);
    expect(periods.map((p) => p.label)).toEqual(['Old English', '1990s']);
    expect(periods[1]).toMatchObject({ total: 4, byShift: { metaphor: 3, metonymy: 1 } });
    expect(shifts).toEqual(['root', 'metaphor', 'metonymy']);
    expect(maxTotal).toBe(4);
    expect(maxCell).toBe(3);
  });

  it('handles an empty lexicon', () => {
    expect(pivotPeriods([])).toEqual({ periods: [], shifts: [], maxTotal: 0, maxCell: 0 });
  });
});

describe('niceCeil', () => {
  it('rounds up to 1, 2 or 5 × 10^k', () => {
    expect([0, 1, 3, 7, 11, 260, 1165].map(niceCeil)).toEqual([1, 1, 5, 10, 20, 500, 2000]);
  });
});

describe('niceAxis', () => {
  it('covers the maximum in clean steps', () => {
    expect(niceAxis(1165)).toEqual({ max: 1500, ticks: [0, 500, 1000, 1500] });
    expect(niceAxis(100)).toEqual({ max: 100, ticks: [0, 50, 100] });
    expect(niceAxis(0)).toEqual({ max: 1, ticks: [0, 1] });
  });
});

describe('heatLevel', () => {
  it('leaves empty cells blank and scales the rest', () => {
    expect(heatLevel(0, 5)).toBe(0);
    expect(heatLevel(5, 5)).toBeCloseTo(0.9);
    expect(heatLevel(1, 5)).toBeGreaterThan(0.16);
  });
});
