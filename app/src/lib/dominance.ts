/**
 * Sense dominance over time, from a kernel density estimate per sense.
 *
 * A sense's evidence is its registration date (its first attestation) plus the year of every dated
 * attestation. Each piece of evidence adds a Gaussian kernel; the sum is masked by the years the
 * sense was in use (registration to obsolescence, with soft edges), so no density predates it.
 * Shares divide each sense's density, plus a small floor for every sense in use, by the total:
 * where no sense has evidence nearby, the senses in use share the word evenly.
 */

export interface DominanceInput {
  id: string;
  date_earliest: number;
  obsolete_year: number | null;
  /** Years of the sense's dated attestations. */
  years: number[];
}

export interface DominanceSeries {
  years: number[];
  /** density[i][k]: kernel density of sense i in years[k], in pieces of evidence (a lone kernel peaks at 1). */
  density: number[][];
  /** shares[i][k]: share of sense i in years[k], 0–1; the senses sum to 1 wherever any is in use, else 0. */
  shares: number[][];
  /** Evidence years per sense: registration first, then attestations. */
  evidence: number[][];
  bandwidth: number;
}

/** Weight of a sense in use but with no evidence nearby, relative to one kernel peak. */
export const FLOOR = 0.05;

const sigmoid = (x: number) => 1 / (1 + Math.exp(-x));

/** Kernel bandwidth in years: about a thirtieth of the span, between 5 and 40. */
export const bandwidthFor = (span: number) => Math.max(5, Math.min(40, Math.round(span / 30)));

export function senseDominance(senses: DominanceInput[], end: number, points = 320): DominanceSeries {
  if (!senses.length) return { years: [], density: [], shares: [], evidence: [], bandwidth: 0 };
  const start = Math.min(...senses.map((s) => s.date_earliest));
  const span = Math.max(1, end - start);
  const h = bandwidthFor(span);
  const edge = Math.max(1, h / 8);
  const n = Math.min(points, span + 1);
  const years = Array.from({ length: n }, (_, k) => (n === 1 ? start : start + (span * k) / (n - 1)));

  const evidence = senses.map((s) => [s.date_earliest, ...s.years.filter((y) => y >= s.date_earliest - h)]);
  const presence = senses.map((s) =>
    years.map((t) => {
      const born = sigmoid((t - s.date_earliest + h / 4) / edge);
      return s.obsolete_year == null ? born : born * sigmoid((s.obsolete_year - t) / edge);
    }),
  );
  const density = evidence.map((ev, i) =>
    years.map((t, k) => presence[i][k] * ev.reduce((sum, y) => sum + Math.exp(-0.5 * ((t - y) / h) ** 2), 0)),
  );
  const weights = density.map((row, i) => row.map((d, k) => d + FLOOR * presence[i][k]));
  const shares = weights.map((w) =>
    w.map((v, k) => {
      // No share until some sense is in use, so a sense never dominates before its registration.
      if (presence.reduce((sum, p) => sum + p[k], 0) < 0.5) return 0;
      const total = weights.reduce((sum, ws) => sum + ws[k], 0);
      return total > 1e-9 ? v / total : 0;
    }),
  );
  return { years, density, shares, evidence, bandwidth: h };
}

/** Index of the largest value in a row. */
export const peakIndex = (row: number[]) => row.reduce((best, v, k) => (v > row[best] ? k : best), 0);
