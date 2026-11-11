import { useState } from 'react';

/**
 * Usages of a candidate sense per crawl year: one series, so no legend; neutral ink like the other
 * statistics charts. Hovering (or focusing) a bar shows its value in the caption line.
 */
export function YearBars({ counts, label }: { counts: Record<string, number>; label: string }) {
  const years = Object.keys(counts).sort();
  const [hover, setHover] = useState<string | null>(null);
  if (!years.length) return null;
  const total = years.reduce((s, y) => s + counts[y], 0);
  const max = Math.max(...years.map((y) => counts[y]));
  const W = 28;
  const GAP = 2;
  const H = 44;
  const width = years.length * (W + GAP) - GAP;
  const pct = (n: number) => `${Math.round((100 * n) / total)}%`;
  const caption = hover
    ? `${hover}: ${counts[hover].toLocaleString()} usages (${pct(counts[hover])})`
    : `Usages per crawl year, ${years[0]}–${years[years.length - 1]}`;

  return (
    <figure className="year-bars">
      <svg
        viewBox={`0 0 ${width} ${H + 14}`}
        width={width}
        height={H + 14}
        role="img"
        aria-label={`${label}: ${years.map((y) => `${y} ${counts[y]}`).join(', ')}`}
        onMouseLeave={() => setHover(null)}
      >
        <line x1={0} x2={width} y1={H + 0.5} y2={H + 0.5} className="year-bars-base" />
        {years.map((y, i) => {
          const h = Math.max(2, Math.round((counts[y] / max) * (H - 4)));
          const x = i * (W + GAP);
          const r = Math.min(4, h / 2);
          return (
            <g
              key={y}
              tabIndex={0}
              onMouseEnter={() => setHover(y)}
              onFocus={() => setHover(y)}
              onBlur={() => setHover(null)}
              className={hover === y ? 'is-hover' : undefined}
            >
              <rect x={x} y={0} width={W} height={H + 14} className="year-bars-hit" />
              <path
                d={`M${x},${H} V${H - h + r} q0,${-r} ${r},${-r} h${W - 2 * r} q${r},0 ${r},${r} V${H} Z`}
                className="year-bars-bar"
              />
              <text x={x + W / 2} y={H + 12} className="year-bars-year">
                {`’${y.slice(2)}`}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="small muted" aria-live="polite">
        {caption}
      </figcaption>
    </figure>
  );
}
