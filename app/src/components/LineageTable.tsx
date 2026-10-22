import { useMemo, useState, type KeyboardEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ancestry, layoutLineage, type GraphItem } from '../lib/graph';
import { branchColor, branchLetter, senseLabel, senseTag } from '../lib/format';
import { useMediaQuery } from '../lib/useMediaQuery';
import type { Sense } from '../lib/types';
import { GraphLegend, LineageGraph } from './LineageGraph';

/** Branch colour at `pct`% over transparent; works with the CSS-variable palette. */
const tint = (color: string, pct: number) => `color-mix(in srgb, ${color} ${pct}%, transparent)`;

export type LineageRow =
  | { kind: 'sense'; sense: Sense; alive: boolean; matches: boolean }
  | { kind: 'today'; label: string };

interface Props {
  rows: LineageRow[];
  /** Direction of the past: -1 when oldest rows are on top. */
  pastDir: 1 | -1;
  extendToToday?: boolean;
  rowH?: number;
}

/** Senses as rows, with the git-style lineage graph drawn in the first column. */
export function LineageTable({ rows, pastDir, extendToToday = false, rowH: rowHProp }: Props) {
  const navigate = useNavigate();
  const narrow = useMediaQuery('(max-width: 720px)');
  const rowH = rowHProp ?? (narrow ? 64 : 56);
  const [hover, setHover] = useState<string | null>(null);

  const items = useMemo<GraphItem[]>(
    () =>
      rows.map((r) =>
        r.kind === 'sense'
          ? {
              kind: 'sense',
              h: rowH,
              sense: {
                id: r.sense.id,
                parents: r.sense.parents.map((p) => p.parent.id),
                branch: r.sense.branch,
                alive: r.alive,
                dimmed: !r.matches,
              },
            }
          : { kind: r.kind, h: 36 },
      ),
    [rows, rowH],
  );

  const layout = useMemo(
    () =>
      layoutLineage(items, {
        rowH,
        pastDir,
        extendToToday,
        laneW: narrow ? 10 : 16,
        pad: narrow ? 10 : 16,
      }),
    [items, rowH, pastDir, extendToToday, narrow],
  );

  const parentsOf = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const r of rows) if (r.kind === 'sense') m.set(r.sense.id, r.sense.parents.map((p) => p.parent.id));
    return (id: string) => m.get(id) ?? [];
  }, [rows]);
  const highlight = useMemo(() => (hover ? ancestry(hover, parentsOf) : null), [hover, parentsOf]);

  const graphW = Math.max(layout.width, narrow ? 40 : 96);
  const cols = narrow ? `${graphW}px minmax(0,1fr) auto` : `${graphW}px minmax(0,1fr) 140px 150px`;

  const onKey = (e: KeyboardEvent<HTMLDivElement>, id: string) => {
    if (e.target !== e.currentTarget) return; // a parent link inside the row handles its own keys
    if (e.key === 'Enter') navigate(`/sense/${id}`);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const all = Array.from(e.currentTarget.parentElement!.querySelectorAll<HTMLElement>('[data-row]'));
      const i = all.indexOf(e.currentTarget);
      all[e.key === 'ArrowDown' ? i + 1 : i - 1]?.focus();
    }
    if (e.key === 'Escape') e.currentTarget.blur();
  };

  return (
    <div className="card lineage">
      <div className="lineage-head" style={{ gridTemplateColumns: cols }}>
        <span className="lineage-head-first">
          Lineage
          {layout.folded ? (
            <span className="lineage-head-fold" title={`${layout.folded} branches folded into the last lane`}>
              {' '}+{layout.folded}
              <span className="sr-only"> branches folded into the last lane</span>
            </span>
          ) : null}
        </span>
        <span>Sense</span>
        {!narrow && <span>Shift</span>}
        <span className="right">Registered</span>
      </div>
      <div className="lineage-body" onMouseLeave={() => setHover(null)}>
        <LineageGraph layout={layout} highlight={highlight} />
        {rows.map((r, i) => {
          if (r.kind === 'today') {
            return (
              <div key="today" className="lineage-today" style={{ gridTemplateColumns: cols, height: 36 }}>
                <span />
                <em>{r.label}</em>
              </div>
            );
          }
          const s = r.sense;
          const color = branchColor(s.branch);
          const x = layout.x(s.id);
          const isHover = hover === s.id;
          const dimmed = highlight && !highlight.has(s.id);
          const opacity = (r.matches ? 1 : 0.4) * (r.alive ? 1 : 0.72) * (dimmed ? 0.55 : 1);
          const parents = s.parents.map((p) => ({ id: p.parent.id, label: senseLabel(p.parent, s.lemma) }));
          const parentText = parents.length ? `from ${parents.map((p) => p.label).join(' and ')}` : 'root sense';
          return (
            <div
              key={s.id}
              data-row
              tabIndex={0}
              className="lineage-row"
              style={{
                gridTemplateColumns: cols,
                height: rowH,
                background: `linear-gradient(90deg, transparent ${x + 10}px, ${tint(color, isHover ? 22 : 10)} ${x + 10}px, ${tint(color, isHover ? 8 : 2.4)} 55%, transparent 85%)`,
              }}
              aria-label={`${s.lemma} ${senseTag(s)}, ${s.gloss}, registered ${s.date_label}, ${parentText}${r.alive ? '' : ', obsolete'}${r.matches ? '' : ', filtered out'}`}
              onMouseEnter={() => setHover(s.id)}
              onFocus={() => setHover(s.id)}
              onClick={() => navigate(`/sense/${s.id}`)}
              onKeyDown={(e) => onKey(e, s.id)}
              data-index={i}
            >
              <span />
              <div className="lineage-main" style={{ opacity }}>
                <div className="lineage-gloss">
                  {s.gloss}
                </div>
                <div className="lineage-meta">
                  <span className="mono fg2">{senseTag(s)}</span>
                  <span aria-hidden="true">·</span>
                  <span>branch {branchLetter(s.branch)}</span>
                  <span aria-hidden="true">·</span>
                  {parents.length ? (
                    <>
                      <span>from</span>
                      {parents.map((p, j) => (
                        <span key={p.id}>
                          {j > 0 && <span aria-hidden="true">+ </span>}
                          <Link className="inline-link" to={`/sense/${p.id}`} onClick={(e) => e.stopPropagation()}>
                            {p.label}
                          </Link>
                        </span>
                      ))}
                    </>
                  ) : (
                    <span>root sense</span>
                  )}
                  {narrow && <span className="chip chip-sm">{s.shift}</span>}
                </div>
              </div>
              {!narrow && (
                <span style={{ opacity }}>
                  <span className="chip">{s.shift}</span>
                </span>
              )}
              <div className="lineage-date" style={{ opacity }}>
                <span className="mono">{s.date_label}</span>
                {!r.alive && s.obsolete_label && <span className="small muted">obsolete {s.obsolete_label}</span>}
              </div>
            </div>
          );
        })}
      </div>
      <GraphLegend />
    </div>
  );
}
