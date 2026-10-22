import { describe, expect, it } from 'vitest';
import { ancestry, layoutLineage, type GraphItem, type GraphSense } from './graph';

const sense = (id: string, parents: string[] = [], o: Partial<GraphSense> = {}): GraphItem => ({
  kind: 'sense',
  h: 56,
  sense: { id, parents, branch: 0, alive: true, dimmed: false, ...o },
});

describe('layoutLineage', () => {
  // cloud: n1 (obsolete root) → n2 → {n3, n4}; n6 merges n5 and n2.
  const items: GraphItem[] = [
    sense('n1', [], { alive: false }),
    sense('n2', ['n1'], { branch: 1 }),
    sense('n3', ['n2'], { branch: 2 }),
    sense('n5', ['n2'], { branch: 3 }),
    sense('n6', ['n5', 'n2'], { branch: 4 }),
    { kind: 'today', h: 36 },
  ];
  const g = layoutLineage(items, { rowH: 56, pastDir: -1, extendToToday: true });

  it('puts a child born from a living parent on its own lane', () => {
    expect(g.x('n3')).not.toBe(g.x('n2'));
    expect(g.x('n5')).not.toBe(g.x('n2'));
  });

  it('reuses the lane of an obsolete sense once its branch ends', () => {
    const r = layoutLineage([sense('old', [], { alive: false }), sense('later'), { kind: 'today', h: 36 }], {
      rowH: 56,
      pastDir: -1,
      extendToToday: true,
    });
    expect(r.x('later')).toBe(r.x('old'));
    expect(g.x('n2')).not.toBe(g.x('n1')); // a child still curves out of its parent's node
  });

  it('draws a curve from the primary parent and a merge from the second parent', () => {
    const keys = g.edges.map((e) => e.key);
    expect(keys).toContain('e:n5>n6');
    expect(keys).toContain('m:n2>n6');
    expect(g.dots.find((d) => d.key === 'n:n6')?.merge).toBe(true);
  });

  it('marks obsolete senses hollow and does not extend them to today', () => {
    expect(g.dots.find((d) => d.key === 'n:n1')?.hollow).toBe(true);
    expect(g.edges.some((e) => e.key === 't:n1')).toBe(false);
    expect(g.edges.some((e) => e.key === 't:n3')).toBe(true);
  });

  it('draws a short stub for a parent outside the loaded rows', () => {
    const s = layoutLineage([sense('a', ['missing'])], { rowH: 56, pastDir: 1 });
    expect(s.edges.find((e) => e.key === 's:a')?.stub).toBe(true);
    expect(s.dots.some((d) => d.stub)).toBe(true);
  });

  it('folds lanes beyond the maximum into a "+n" marker', () => {
    const many: GraphItem[] = [sense('root')];
    for (let i = 0; i < 11; i++) many.push(sense(`c${i}`, ['root']));
    many.push({ kind: 'today', h: 36 });
    const f = layoutLineage(many, { rowH: 56, pastDir: -1, extendToToday: true, maxLanes: 8 });
    expect(f.folded).toBe(12 - 7);
    expect(f.width).toBe(16 * 2 + 7 * 16);
    expect(Math.max(...f.dots.map((d) => d.cx))).toBe(16 + 7 * 16);
  });
});

describe('ancestry', () => {
  it('collects every ancestor across merges', () => {
    const parents: Record<string, string[]> = { n6: ['n5', 'n2'], n5: ['n2'], n2: ['n1'], n1: [] };
    expect([...ancestry('n6', (id) => parents[id] ?? [])].sort()).toEqual(['n1', 'n2', 'n5', 'n6']);
  });
});
