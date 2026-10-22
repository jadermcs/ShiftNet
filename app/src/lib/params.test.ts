import { describe, expect, it } from 'vitest';
import { matchesFilters, parseParams, toSearch } from './params';

describe('view params', () => {
  it('round-trips through the URL and drops defaults', () => {
    const p = parseParams(new URLSearchParams('view=timeline&order=desc&at=1600&pos=noun,verb&shift=metaphor&from=1200'));
    expect(p).toMatchObject({ view: 'timeline', order: 'desc', at: 1600, pos: ['noun', 'verb'], shift: ['metaphor'], from: 1200, to: null });
    expect(toSearch(p)).toBe('?view=timeline&order=desc&at=1600&pos=noun%2Cverb&shift=metaphor&from=1200');
    expect(toSearch({ ...p, view: 'senses', order: 'asc', at: null, pos: [], shift: [], from: null })).toBe('');
  });

  it('ignores unknown values', () => {
    const p = parseParams(new URLSearchParams('pos=noun,banana&at=abc&shift=sideways'));
    expect(p.pos).toEqual(['noun']);
    expect(p.at).toBeNull();
    expect(p.shift).toEqual([]);
  });

  it('matches filters', () => {
    const f = { pos: ['noun' as const], shift: [], from: 1500, to: null };
    expect(matchesFilters(f, { pos: 'noun', shift: 'metaphor', date_earliest: 1990 })).toBe(true);
    expect(matchesFilters(f, { pos: 'verb', shift: 'metaphor', date_earliest: 1990 })).toBe(false);
    expect(matchesFilters(f, { pos: 'noun', shift: 'metaphor', date_earliest: 1300 })).toBe(false);
  });
});
