import type { CSSProperties } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchStats } from '../lib/api';
import { plural } from '../lib/format';
import { HEAT_DARK_INK, heatLevel, niceAxis, pivotPeriods } from '../lib/stats';
import { POS_ORDER, type LexiconStats } from '../lib/types';
import { useCrumbs } from '../components/Shell';
import { ErrorState, Loading } from '../components/States';

/** Lexicon-wide figures: when senses appeared, by which kind of shift, and how long change took. */
export function StatsPage() {
  useCrumbs([{ label: 'Statistics' }]);
  const stats = useQuery({ queryKey: ['stats'], queryFn: fetchStats });

  return (
    <>
      <div className="card page-head">
        <h1 className="h-page">Statistics</h1>
        <p className="muted">
          Figures across the whole lexicon. Change is measured along each sense's main parent link, the branch it grows
          from in the lineage graph.
        </p>
      </div>
      {stats.isPending && <Loading label="Loading statistics…" rows={3} />}
      {stats.isError && <ErrorState error={stats.error} retry={() => stats.refetch()} />}
      {stats.data && <Figures stats={stats.data} />}
    </>
  );
}

function Figures({ stats }: { stats: LexiconStats }) {
  const o = stats.overview;
  if (o.senses === 0) return <div className="card state muted">No senses registered yet.</div>;
  return (
    <>
      <div className="stat-tiles">
        <Tile label="Senses" value={o.senses} note={`in ${plural(o.words, 'word')}`} />
        <Tile label="Parent links" value={o.links} note={`${o.cross_word} across words`} />
        <Tile
          label="Median time to a new sense"
          value={o.median_gap == null ? '—' : `${o.median_gap} yrs`}
          note="from parent sense to child"
        />
        <Tile label="Obsolete senses" value={o.obsolete} note={`${Math.round((100 * o.obsolete) / o.senses)}% of all senses`} />
        <Tile label="Part of speech changes" value={o.pos_changes} note={`of ${plural(o.links, 'link')}`} />
      </div>
      <PeriodTable stats={stats} />
      <GapChart stats={stats} />
      <PosMatrix stats={stats} />
    </>
  );
}

function Tile({ label, value, note }: { label: string; value: number | string; note: string }) {
  return (
    <div className="card stat-tile">
      <span className="muted small">{label}</span>
      <span className="stat-value">{value}</span>
      <span className="muted small">{note}</span>
    </div>
  );
}

const heatStyle = (v: number, max: number): CSSProperties => {
  const level = heatLevel(v, max);
  return level
    ? {
        background: `color-mix(in srgb, var(--sn-fg) ${Math.round(level * 100)}%, var(--sn-surface))`,
        color: level > HEAT_DARK_INK ? 'var(--sn-bg)' : 'var(--sn-fg)',
      }
    : {};
};

/** New senses per period, with the shift types behind them as a heat table. */
function PeriodTable({ stats }: { stats: LexiconStats }) {
  const { periods, shifts, maxTotal, maxCell } = pivotPeriods(stats.periods);
  return (
    <section className="card stats-card" aria-labelledby="periods-h">
      <div className="stack-4">
        <h2 id="periods-h">New senses by period</h2>
        <p className="small muted">
          Centuries before 1900, decades after. Darker cells hold more senses; root senses have no parent.
        </p>
      </div>
      <div className="table-scroll">
        <table className="heat-table">
          <thead>
            <tr>
              <th scope="col">Period</th>
              <th scope="col" className="heat-total-head">
                New senses
              </th>
              {shifts.map((s) => (
                <th key={s} scope="col" className="heat-head">
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {periods.map((p) => (
              <tr key={p.label}>
                <th scope="row" className="mono nowrap">
                  {p.label}
                </th>
                <td className="heat-total">
                  <span className="bar" style={{ width: `${(100 * p.total) / maxTotal}%` }} aria-hidden="true" />
                  <span className="mono small">{p.total}</span>
                </td>
                {shifts.map((s) => {
                  const v = p.byShift[s] ?? 0;
                  return (
                    <td key={s} className="heat-cell mono small" style={heatStyle(v, maxCell)} title={`${p.label}, ${s}: ${v}`}>
                      {v || <span className="sr-only">0</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Years between a sense and its parent, per shift type: range from fastest to slowest, dot at the median. */
function GapChart({ stats }: { stats: LexiconStats }) {
  const rows = stats.shifts.filter((s) => s.shift !== 'root' && s.median_gap != null);
  if (!rows.length) return null;
  const { max, ticks } = niceAxis(Math.max(...rows.map((r) => r.max_gap ?? 0)));
  const pct = (v: number) => `${(100 * v) / max}%`;
  return (
    <section className="card stats-card" aria-labelledby="gap-h">
      <div className="stack-4">
        <h2 id="gap-h">Years from parent to child sense</h2>
        <p className="small muted">
          Line: fastest to slowest shift of each type. Dot: median, in years, followed by the number of senses.
        </p>
      </div>
      <div className="gap-chart">
        {rows.map((r) => {
          const desc = `${r.shift}: median ${r.median_gap} years, from ${r.min_gap} to ${r.max_gap}, ${plural(r.senses, 'sense')}`;
          return (
            <div key={r.shift} className="gap-row" tabIndex={0} title={desc} aria-label={desc}>
              <span className="chip">{r.shift}</span>
              <div className="gap-track" aria-hidden="true">
                <span className="gap-range" style={{ left: pct(r.min_gap!), width: pct(r.max_gap! - r.min_gap!) }} />
                <span className="gap-median" style={{ left: pct(r.median_gap!) }} />
              </div>
              <span className="mono small nowrap">
                {r.median_gap} yrs <span className="muted">· {r.senses}</span>
              </span>
            </div>
          );
        })}
        <div className="gap-row gap-axis" aria-hidden="true">
          <span />
          <div className="gap-track">
            {ticks.map((t) => (
              <span key={t} className="gap-tick mono" style={{ left: pct(t) }}>
                {t}
              </span>
            ))}
          </div>
          <span />
        </div>
      </div>
    </section>
  );
}

/** Part of speech of the parent sense against the child's: off the diagonal, the shift changed word class. */
function PosMatrix({ stats }: { stats: LexiconStats }) {
  const count = (from: string, to: string) =>
    stats.transitions.find((t) => t.from_pos === from && t.to_pos === to)?.links ?? 0;
  const max = Math.max(0, ...stats.transitions.map((t) => t.links));
  const used = POS_ORDER.filter((p) => stats.transitions.some((t) => t.from_pos === p || t.to_pos === p));
  if (!used.length) return null;
  return (
    <section className="card stats-card" aria-labelledby="pos-h">
      <div className="stack-4">
        <h2 id="pos-h">Part of speech, parent to child</h2>
        <p className="small muted">
          {plural(stats.overview.pos_changes, 'link')} of {stats.overview.links} cross a part of speech, as{' '}
          <em>mouse</em> the device became the verb <em>to mouse</em>.
        </p>
      </div>
      <div className="table-scroll">
        <table className="heat-table pos-table">
          <thead>
            <tr>
              <th scope="col">
                <span className="sr-only">Parent part of speech</span>
                <span aria-hidden="true">parent ↓ child →</span>
              </th>
              {used.map((p) => (
                <th key={p} scope="col" className="heat-head">
                  {p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {used.map((from) => (
              <tr key={from}>
                <th scope="row">{from}</th>
                {used.map((to) => {
                  const v = count(from, to);
                  return (
                    <td
                      key={to}
                      className={`heat-cell mono small${from === to ? ' heat-same' : ''}`}
                      style={heatStyle(v, max)}
                      title={`${from} → ${to}: ${v}`}
                    >
                      {v}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
