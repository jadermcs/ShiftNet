// Git-style lineage layout. Pure geometry: rows in, lanes / paths / dots out.
//
// Each sense owns a lane from its primary parent's row down (or up) to the last row
// that needs it: a merge into a later sense, or the "today" row while it is still in use.
// Lanes are reused greedily once free, like `git log --graph`.

import { branchColor } from './format';

export interface GraphSense {
  id: string;
  /** Primary parent first; further parents are merged in. */
  parents: string[];
  branch: number;
  /** false = obsolete at the time shown: hollow node, branch ends. */
  alive: boolean;
  /** Filtered out: dashed node and connectors. */
  dimmed: boolean;
}

export type GraphItem =
  | { kind: 'sense'; sense: GraphSense; h: number }
  | { kind: 'today'; h: number };

export interface LayoutOptions {
  rowH: number;
  laneW?: number;
  pad?: number;
  /** Draw living branches down/up to the "today" row. */
  extendToToday?: boolean;
  /** Direction of the past: -1 when oldest rows are on top, 1 when newest are on top. */
  pastDir: 1 | -1;
  maxLanes?: number;
}

export interface Edge {
  key: string;
  d: string;
  color: string;
  /** Highlighted only when every id is in the highlighted set. */
  ids: string[];
  dashed: boolean;
  /** Short dotted stub for a parent outside the loaded rows. */
  stub?: boolean;
}

export interface Dot {
  key: string;
  id: string;
  cx: number;
  cy: number;
  color: string;
  hollow: boolean;
  dashed: boolean;
  merge: boolean;
  /** End of a stub, parent not loaded. */
  stub?: boolean;
}

export interface Layout {
  width: number;
  height: number;
  centers: number[];
  rowOf: Record<string, number>;
  x: (id: string) => number;
  edges: Edge[];
  dots: Dot[];
  /** Branches folded into the last lane when more than maxLanes are open at once. */
  folded: number;
}

export function layoutLineage(items: GraphItem[], o: LayoutOptions): Layout {
  const laneW = o.laneW ?? 16;
  const pad = o.pad ?? 16;
  const maxLanes = o.maxLanes ?? 8;

  let y = 0;
  const centers = items.map((it) => {
    const c = y + it.h / 2;
    y += it.h;
    return c;
  });
  const height = y;

  const rowOf: Record<string, number> = {};
  const senses: { s: GraphSense; i: number }[] = [];
  items.forEach((it, i) => {
    if (it.kind === 'sense') {
      rowOf[it.sense.id] = i;
      senses.push({ s: it.sense, i });
    }
  });
  const byId = new Map(senses.map(({ s }) => [s.id, s]));
  const todayRow = items.findIndex((it) => it.kind === 'today');

  // Row interval each sense's lane must stay reserved for.
  const span: Record<string, { a: number; b: number }> = {};
  for (const { s, i } of senses) span[s.id] = { a: i, b: i };
  const extend = (id: string, row: number) => {
    const v = span[id];
    if (row < v.a) v.a = row;
    if (row > v.b) v.b = row;
  };
  for (const { s, i } of senses) {
    const loaded = s.parents.filter((p) => p in rowOf);
    if (loaded[0]) extend(s.id, rowOf[loaded[0]]);
    for (const p of loaded.slice(1)) extend(p, i);
    if (o.extendToToday && todayRow >= 0 && s.alive) extend(s.id, todayRow);
  }

  const order = senses.map(({ s }) => s.id).sort((p, q) => span[p].a - span[q].a || rowOf[p] - rowOf[q]);
  const ends: number[] = [];
  const lane: Record<string, number> = {};
  for (const id of order) {
    let L = ends.findIndex((e) => e < span[id].a);
    if (L < 0) {
      L = ends.length;
      ends.push(0);
    }
    ends[L] = span[id].b;
    lane[id] = L;
  }

  const laneCount = Math.max(1, ends.length);
  const shown = Math.min(laneCount, maxLanes);
  const folded = laneCount > maxLanes ? laneCount - (maxLanes - 1) : 0;
  const x = (id: string) => pad + Math.min(lane[id] ?? 0, shown - 1) * laneW;
  const width = pad * 2 + (shown - 1) * laneW;

  const edges: Edge[] = [];
  const dots: Dot[] = [];
  const rh = o.rowH;

  for (const { s, i } of senses) {
    const color = branchColor(s.branch);
    const xc = x(s.id);
    const yc = centers[i];
    const loaded = s.parents.filter((p) => p in rowOf);

    loaded.forEach((p, j) => {
      const xp = x(p);
      const ya = centers[rowOf[p]];
      const dir = Math.sign(yc - ya) || 1;
      const k = Math.min(rh * 0.8, Math.abs(yc - ya));
      const parent = byId.get(p)!;
      if (j === 0) {
        // New branch curves out of the parent's node, then runs straight to the child.
        edges.push({
          key: `e:${p}>${s.id}`,
          d: `M${xp} ${ya} C${xp} ${ya + dir * k * 0.5} ${xc} ${ya + dir * k * 0.5} ${xc} ${ya + dir * k} L${xc} ${yc}`,
          color,
          ids: [p, s.id],
          dashed: s.dimmed,
        });
      } else {
        // Merge: the other parent's lane runs on, then curves into the child.
        edges.push({
          key: `m:${p}>${s.id}`,
          d: `M${xp} ${ya} L${xp} ${yc - dir * k} C${xp} ${yc - dir * k * 0.5} ${xc} ${yc - dir * k * 0.5} ${xc} ${yc}`,
          color: branchColor(parent.branch),
          ids: [p, s.id],
          dashed: s.dimmed || parent.dimmed,
        });
      }
    });

    if (o.extendToToday && todayRow >= 0 && s.alive) {
      edges.push({ key: `t:${s.id}`, d: `M${xc} ${yc} L${xc} ${centers[todayRow]}`, color, ids: [s.id], dashed: s.dimmed });
    }

    if (s.parents.some((p) => !(p in rowOf))) {
      const ye = yc + o.pastDir * rh * 0.42;
      edges.push({ key: `s:${s.id}`, d: `M${xc} ${yc} L${xc} ${ye}`, color, ids: [s.id], dashed: true, stub: true });
      dots.push({ key: `so:${s.id}`, id: s.id, cx: xc, cy: ye, color, hollow: true, dashed: false, merge: false, stub: true });
    }

    dots.push({
      key: `n:${s.id}`,
      id: s.id,
      cx: xc,
      cy: yc,
      color,
      hollow: !s.alive,
      dashed: s.dimmed,
      merge: loaded.length > 1,
    });
  }

  return { width, height, centers, rowOf, x, edges, dots, folded };
}

/** The sense and every ancestor reachable through the given parent map. */
export function ancestry(id: string, parentsOf: (id: string) => string[]): Set<string> {
  const seen = new Set([id]);
  const stack = [id];
  while (stack.length) {
    for (const p of parentsOf(stack.pop()!)) {
      if (!seen.has(p)) {
        seen.add(p);
        stack.push(p);
      }
    }
  }
  return seen;
}
