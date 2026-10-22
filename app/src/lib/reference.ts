import { normalize } from './format';
import type { Attestation, Reference } from './types';

/** Date of a quoted use as recorded, else its year, else the work's date. */
export const attestationDate = (a: Attestation) =>
  a.date_label ?? (a.year != null ? String(a.year) : (a.source.published_label ?? a.source.published_year?.toString() ?? null));

/** Plain-text reference, e.g. "Darwin, Charles. On the Origin of Species. John Murray, 1859." */
export function referenceText(r: Reference, locator?: string | null) {
  const date = r.published_label ?? r.published_year?.toString();
  const parts = [r.author, r.title, [r.publisher, date].filter(Boolean).join(', '), locator, r.identifier];
  return parts.filter(Boolean).join('. ') + '.';
}

/** Host name shown for a link, e.g. "w3.org". */
export const hostOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
};

/**
 * Splits a quote into plain and highlighted parts: words that start with the lemma
 * ("cloud", "clouds", "clouded"), ignoring case and accents. Multi-word lemmas match as a phrase.
 */
export function highlightLemma(quote: string, lemma: string): { text: string; hit: boolean }[] {
  const key = normalize(lemma);
  if (!key) return [{ text: quote, hit: false }];
  const folded = normalize(quote);
  // normalize() can change lengths for some characters; only highlight when offsets line up.
  if (folded.length !== quote.length) return [{ text: quote, hit: false }];
  const out: { text: string; hit: boolean }[] = [];
  const word = /[\p{L}\p{N}'’-]/u;
  let last = 0;
  for (let i = folded.indexOf(key); i >= 0; i = folded.indexOf(key, i + 1)) {
    if (i < last || (i > 0 && word.test(folded[i - 1]))) continue;
    let end = i + key.length;
    while (end < folded.length && /[\p{L}]/u.test(folded[end])) end++;
    if (i > last) out.push({ text: quote.slice(last, i), hit: false });
    out.push({ text: quote.slice(i, end), hit: true });
    last = end;
  }
  if (last < quote.length) out.push({ text: quote.slice(last), hit: false });
  return out;
}
