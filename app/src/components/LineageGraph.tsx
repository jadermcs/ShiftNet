import type { Layout } from '../lib/graph';
import { branchColor } from '../lib/format';

/* Colours go through `style` (not presentation attributes) so CSS variables resolve and follow the theme. */
const BG = 'var(--sn-surface)';
const FG = 'var(--sn-fg)';

interface Props {
  layout: Layout;
  /** Ancestry being traced; everything else drops to 16%. */
  highlight: Set<string> | null;
  current?: string;
}

/** SVG overlay drawn behind the rows. Decorative: every row states its parent in text. */
export function LineageGraph({ layout, highlight, current }: Props) {
  const on = (ids: string[]) => !highlight || ids.every((id) => highlight.has(id));
  const op = (ids: string[]) => (on(ids) ? 1 : 0.16);

  return (
    <svg
      className="lineage-svg"
      width={layout.width}
      height={layout.height}
      aria-hidden="true"
      focusable="false"
    >
      {layout.edges.map((e) => (
        <path
          key={e.key}
          d={e.d}
          fill="none"
          style={{ stroke: e.color }}
          strokeWidth={2}
          strokeLinecap="round"
          strokeDasharray={e.stub ? '2 3' : e.dashed ? '3 4' : undefined}
          opacity={op(e.ids) * (e.dashed && !e.stub ? 0.55 : 1)}
        />
      ))}
      {layout.dots.map((d) => {
        const o = op([d.id]);
        if (d.stub) {
          return <circle key={d.key} cx={d.cx} cy={d.cy} r={2.5} style={{ fill: BG, stroke: d.color }} strokeWidth={1.5} opacity={o} />;
        }
        return (
          <g key={d.key} opacity={o}>
            {d.merge && <circle cx={d.cx} cy={d.cy} r={9} style={{ fill: BG, stroke: d.color }} strokeWidth={1.5} />}
            {current === d.id && (
              <circle cx={d.cx} cy={d.cy} r={d.merge ? 12 : 10} fill="none" style={{ stroke: FG }} strokeWidth={1.5} />
            )}
            <circle
              cx={d.cx}
              cy={d.cy}
              r={5.5}
              style={{ fill: d.hollow ? BG : d.color, stroke: d.color }}
              strokeWidth={2}
              strokeDasharray={d.dashed ? '2 2' : undefined}
              opacity={d.dashed ? 0.6 : 1}
            />
          </g>
        );
      })}
    </svg>
  );
}

const [A, B, C, D, E] = [0, 1, 2, 3, 4].map(branchColor);

export function GraphLegend() {
  return (
    <div className="legend">
      <span>
        <svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5" style={{ fill: A }} /></svg>
        in use
      </span>
      <span>
        <svg width="14" height="14" aria-hidden="true">
          <circle cx="7" cy="7" r="4.5" style={{ fill: 'var(--sn-bg)', stroke: B }} strokeWidth="2" />
        </svg>
        obsolete, branch ends
      </span>
      <span>
        <svg width="20" height="20" aria-hidden="true">
          <circle cx="10" cy="10" r="8" fill="none" style={{ stroke: C }} strokeWidth="1.5" />
          <circle cx="10" cy="10" r="4.5" style={{ fill: C }} />
        </svg>
        merge of two senses
      </span>
      <span>
        <svg width="22" height="10" aria-hidden="true">
          <line x1="1" y1="5" x2="21" y2="5" style={{ stroke: D }} strokeWidth="2" strokeDasharray="3 4" />
        </svg>
        filtered out
      </span>
      <span>
        <svg width="12" height="22" aria-hidden="true">
          <line x1="6" y1="11" x2="6" y2="2" style={{ stroke: E }} strokeWidth="2" strokeDasharray="2 3" />
          <circle cx="6" cy="2.5" r="2" style={{ fill: BG, stroke: E }} strokeWidth="1.5" />
          <circle cx="6" cy="16" r="4.5" style={{ fill: E }} />
        </svg>
        parent outside the loaded rows
      </span>
      <span className="legend-hint">Hover or focus a row to trace its ancestry</span>
    </div>
  );
}
