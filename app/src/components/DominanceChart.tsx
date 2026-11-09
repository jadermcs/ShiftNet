import { useMemo, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchAttestationYears } from '../lib/api';
import { peakIndex, senseDominance } from '../lib/dominance';
import { branchColor, CURRENT_YEAR, plural, senseTag } from '../lib/format';
import type { Sense } from '../lib/types';

const W = 1000;
const H = 100;
const pct = (v: number) => `${(v * 100).toFixed(2)}%`;
const share = (v: number) => `${Math.round(v * 100)}%`;
const yearLabel = (y: number) => (Math.round(y) >= CURRENT_YEAR ? 'today' : String(Math.round(y)));

/** Round year ticks, at most about six, between start and end. */
function yearTicks(start: number, end: number) {
  const step = [10, 20, 25, 50, 100, 200, 250, 500, 1000].find((s) => (end - start) / s <= 6) ?? 1000;
  const out: number[] = [];
  for (let y = Math.ceil(start / step) * step; y <= end; y += step) out.push(y);
  return out;
}

/** Plot coordinates of values (0–1 of the plot height) along the x grid. */
const points = (vals: number[]) =>
  vals.map((v, k) => `${((k / (vals.length - 1)) * W).toFixed(1)},${(H * (1 - v)).toFixed(2)}`);

/**
 * Which sense of a word dominated when: each sense's share of the word, stacked so every year sums
 * to 100%. Shares come from a smoothed (kernel) estimate over each sense's registration and attestations.
 */
export function DominanceChart({ senses, lemma }: { senses: Sense[]; lemma: string }) {
  const ids = useMemo(() => senses.map((s) => s.id), [senses]);
  const att = useQuery({ queryKey: ['attestation-years', ids], queryFn: () => fetchAttestationYears(ids) });
  const [hover, setHover] = useState<number | null>(null);
  const [focus, setFocus] = useState<string | null>(null);

  const { years, shares, evidence, bandwidth } = useMemo(
    () =>
      senseDominance(
        senses.map((s) => ({
          id: s.id,
          date_earliest: s.date_earliest,
          obsolete_year: s.obsolete_year,
          years: (att.data ?? []).filter((a) => a.sense_id === s.id).map((a) => a.year),
        })),
        CURRENT_YEAR,
      ),
    [senses, att.data],
  );

  const bands = useMemo(() => {
    const below = years.map(() => 0);
    return shares.map((row) => {
      const lo = [...below];
      row.forEach((v, k) => (below[k] += v));
      const hi = [...below];
      return { d: `M${points(hi).join('L')}L${points(lo).reverse().join('L')}Z`, lo, hi };
    });
  }, [years, shares]);

  if (senses.length < 2 || years.length < 2) return null;

  const start = years[0];
  const xOf = (year: number) => (year - start) / (CURRENT_YEAR - start);
  const last = years.length - 1;
  const attested = att.data?.length ?? 0;
  const peaks = shares.map((row) => peakIndex(row));

  const pick = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setHover(Math.round(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * last));
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      const dir = e.key === 'ArrowRight' ? 1 : -1;
      const step = e.shiftKey ? 10 : 1;
      setHover((h) => Math.max(0, Math.min(last, (h ?? (dir > 0 ? -1 : last + 1)) + dir * step)));
    } else if (e.key === 'Escape') setHover(null);
  };
  const dim = (id: string) => (focus && focus !== id ? 0.25 : 1);

  const k = hover;
  const ranked =
    k == null
      ? []
      : senses
          .map((s, i) => ({ s, v: shares[i][k] }))
          .filter((r) => r.v >= 0.005)
          .sort((a, b) => b.v - a.v);

  return (
    <section className="card dominance" aria-labelledby="dominance-h">
      <div className="stack-4">
        <h2 id="dominance-h">Sense dominance over time</h2>
        <p className="small muted">
          Each band is one sense's share of <em>{lemma}</em>; every year adds up to 100%. Shares are smoothed over
          each sense's registration date and dated attestations (±{bandwidth} years, {plural(attested, 'attestation')}
          ), so a sense quoted often around a year takes more of it. Ticks below mark that evidence.
        </p>
      </div>

      <div className="dominance-frame">
        <div className="dominance-yaxis mono" aria-hidden="true">
          <span style={{ top: '0%' }}>100%</span>
          <span style={{ top: '50%' }}>50%</span>
          <span style={{ top: '100%' }}>0%</span>
        </div>
        <div className="min0">
          <div
            className="dominance-plot"
            tabIndex={0}
            role="img"
            aria-label={`Share of each sense of ${lemma} from ${start} to today, summing to 100%. Use the arrow keys to read a year.`}
            onPointerMove={pick}
            onPointerLeave={() => setHover(null)}
            onKeyDown={key}
            onBlur={() => setHover(null)}
          >
            <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
              {bands.map((b, i) => (
                <path
                  key={senses[i].id}
                  d={b.d}
                  fill={branchColor(senses[i].branch)}
                  className="dominance-band"
                  opacity={dim(senses[i].id)}
                />
              ))}
            </svg>
            <span className="dominance-mid" aria-hidden="true" />
            {senses.map((s, i) => {
              const p = peaks[i];
              if (shares[i][p] < 0.2) return null;
              const mid = (bands[i].lo[p] + bands[i].hi[p]) / 2;
              return (
                <span
                  key={s.id}
                  className="dominance-label mono"
                  style={{ left: pct(Math.min(0.94, Math.max(0.04, p / last))), top: pct(1 - mid) }}
                  aria-hidden="true"
                >
                  {senseTag(s)}
                </span>
              );
            })}
            {k != null && (
              <>
                <span className="dominance-cursor" style={{ left: pct(k / last) }} aria-hidden="true" />
                <div className={`dominance-tip${k / last > 0.6 ? ' flip' : ''}`} style={{ left: pct(k / last) }} role="status">
                  <span className="mono small fg">{yearLabel(years[k])}</span>
                  {ranked.map(({ s, v }) => (
                    <span key={s.id} className="dominance-tip-row small">
                      <span className="dot" style={{ background: branchColor(s.branch) }} />
                      <span className="mono">{senseTag(s)}</span>
                      <span className="ellipsis muted">{s.gloss}</span>
                      <span className="mono push-right">{share(v)}</span>
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
          <div className="dominance-rug" aria-hidden="true">
            {evidence.flatMap((ev, i) =>
              ev.map((y, j) => (
                <span
                  key={`${senses[i].id}-${j}`}
                  className={j === 0 ? 'registered' : undefined}
                  style={{ left: pct(xOf(y)), background: branchColor(senses[i].branch), opacity: dim(senses[i].id) }}
                />
              )),
            )}
          </div>
          <div className="dominance-axis mono" aria-hidden="true">
            {yearTicks(start, CURRENT_YEAR).map((t) => (
              <span key={t} style={{ left: pct(xOf(t)) }}>
                {t}
              </span>
            ))}
          </div>
        </div>
      </div>

      <ul className="dominance-legend" aria-label="Senses">
        {senses.map((s, i) => (
          <li key={s.id} onPointerEnter={() => setFocus(s.id)} onPointerLeave={() => setFocus(null)} className="small">
            <span className="dot" style={{ background: branchColor(s.branch) }} aria-hidden="true" />
            <span className="mono">{senseTag(s)}</span>
            <span className="ellipsis muted">{s.gloss}</span>
            <span className="mono fg2 nowrap">
              peak {share(shares[i][peaks[i]])} in {yearLabel(years[peaks[i]])}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
