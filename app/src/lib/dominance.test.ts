import { describe, expect, it } from 'vitest';
import { bandwidthFor, peakIndex, senseDominance } from './dominance';

const at = (years: number[], y: number) => years.reduce((b, v, k) => (Math.abs(v - y) < Math.abs(years[b] - y) ? k : b), 0);

describe('senseDominance', () => {
  it('sums to one wherever a sense is in use', () => {
    const { shares, years } = senseDominance(
      [
        { id: 'a', date_earliest: 1500, obsolete_year: null, years: [] },
        { id: 'b', date_earliest: 1800, obsolete_year: 1900, years: [1850] },
      ],
      2000,
    );
    years.forEach((_, k) => expect(shares[0][k] + shares[1][k]).toBeCloseTo(1, 6));
  });

  it('splits evenly without attestations, and gives way to newer senses', () => {
    const { shares, years } = senseDominance(
      [
        { id: 'a', date_earliest: 1500, obsolete_year: null, years: [] },
        { id: 'b', date_earliest: 1800, obsolete_year: null, years: [] },
      ],
      2000,
    );
    expect(shares[0][at(years, 1600)]).toBeCloseTo(1, 3);
    expect(shares[0][at(years, 1950)]).toBeCloseTo(0.5, 3);
  });

  it('drops an obsolete sense and favours a well-attested one', () => {
    const { shares, years } = senseDominance(
      [
        { id: 'a', date_earliest: 1500, obsolete_year: 1700, years: [] },
        { id: 'b', date_earliest: 1500, obsolete_year: null, years: [] },
        { id: 'c', date_earliest: 1500, obsolete_year: null, years: [1900, 1905, 1910] },
      ],
      2000,
    );
    expect(shares[0][at(years, 1900)]).toBeLessThan(0.001);
    expect(shares[2][at(years, 1905)]).toBeGreaterThan(0.7);
    expect(years[peakIndex(shares[2])]).toBeGreaterThan(1880);
  });

  it('puts a kernel on the registration date and on each attestation', () => {
    const { density, years, evidence } = senseDominance(
      [
        { id: 'a', date_earliest: 1500, obsolete_year: null, years: [1800, 1800] },
        { id: 'b', date_earliest: 1600, obsolete_year: null, years: [] },
      ],
      2000,
    );
    expect(evidence[0]).toEqual([1500, 1800, 1800]);
    expect(density[0][at(years, 1800)]).toBeCloseTo(2, 1);
    expect(density[0][at(years, 1650)]).toBeLessThan(0.01);
    expect(density[1][at(years, 1600)]).toBeGreaterThan(0.7);
    expect(density[1][at(years, 1520)]).toBeLessThan(1e-6);
  });

  it('keeps the bandwidth between 5 and 40 years', () => {
    expect(bandwidthFor(30)).toBe(5);
    expect(bandwidthFor(600)).toBe(20);
    expect(bandwidthFor(3000)).toBe(40);
  });
});

describe('senseDominance from the oldest sense', () => {
  it('fills the whole year range, starting with the oldest sense', () => {
    const { shares, years } = senseDominance([{ id: 'a', date_earliest: 1300, obsolete_year: null, years: [] }, { id: 'b', date_earliest: 1900, obsolete_year: null, years: [] }], 2000);
    expect(years[0]).toBe(1300);
    expect(shares[0][0]).toBeCloseTo(1, 6);
    years.forEach((_, k) => expect(shares[0][k] + shares[1][k]).toBeCloseTo(1, 6));
  });
});
