import { describe, expect, it } from 'vitest';
import { highlightLemma, hostOf, referenceText } from './reference';
import type { Reference } from './types';

const hits = (quote: string, lemma: string) => highlightLemma(quote, lemma).filter((p) => p.hit).map((p) => p.text);

describe('highlightLemma', () => {
  it('marks the lemma and its inflections, ignoring case', () => {
    expect(hits('And all the Clouds that lour’d; a cloud, clouded', 'cloud')).toEqual(['Clouds', 'cloud', 'clouded']);
  });
  it('does not mark the lemma inside another word', () => {
    expect(hits('a thundercloud overhead', 'cloud')).toEqual([]);
  });
  it('keeps the whole quote when parts are joined', () => {
    const q = 'back up your photos to the cloud computing service';
    expect(highlightLemma(q, 'cloud computing').map((p) => p.text).join('')).toBe(q);
    expect(hits(q, 'cloud computing')).toEqual(['cloud computing']);
  });
});

describe('references', () => {
  const r: Reference = {
    id: 'x', kind: 'book', title: 'On the Origin of Species', author: 'Charles Darwin', publisher: 'John Murray',
    published_label: '1859', published_year: 1859, url: null, identifier: null, accessed_on: null,
  };
  it('formats a plain-text reference', () => {
    expect(referenceText(r, 'ch. 3')).toBe('Charles Darwin. On the Origin of Species. John Murray, 1859. ch. 3.');
  });
  it('shows a short host for links', () => {
    expect(hostOf('https://www.w3.org/Proposal.html')).toBe('w3.org');
  });
});
