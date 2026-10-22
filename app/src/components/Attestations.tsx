import { BookOpen, ExternalLink, FileText, Globe, Landmark, Library, Newspaper, ScrollText, type LucideIcon } from 'lucide-react';
import { attestationDate, highlightLemma, hostOf, referenceText } from '../lib/reference';
import type { Attestation, ReferenceKind } from '../lib/types';
import { ValidationBadge } from './ValidationBadge';

const KIND_ICON: Record<ReferenceKind, LucideIcon> = {
  book: BookOpen,
  website: Globe,
  article: FileText,
  journal: FileText,
  newspaper: Newspaper,
  dictionary: Library,
  corpus: Library,
  archive: Landmark,
  other: ScrollText,
};

/** A quotation with its date, reference and validation state. */
export function AttestationItem({ a, lemma, compact = false }: { a: Attestation; lemma: string; compact?: boolean }) {
  const r = a.source;
  const Icon = KIND_ICON[r.kind];
  const date = attestationDate(a);
  const published = r.published_label ?? r.published_year;

  const kind = (
    <span className="source-type" title={`Reference kind: ${r.kind}`}>
      <Icon size={11} aria-hidden="true" />
      {r.kind}
    </span>
  );
  const cite = (
    <cite>
      {r.author && <span>{r.author}, </span>}
      <span className="attestation-title">{r.title}</span>
      {!compact && r.publisher && <span>, {r.publisher}</span>}
      {!compact && published != null && <span> ({published})</span>}
      {a.locator && <span>, {a.locator}</span>}
    </cite>
  );
  const link = r.url && (
    <a href={r.url} target="_blank" rel="noopener noreferrer" className="inline-link attestation-url" title={referenceText(r, a.locator)}>
      {hostOf(r.url)}
      <ExternalLink size={11} aria-hidden="true" />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
  // Contributed rows keep their label everywhere; editorial ones shrink to an icon in compact lists.
  const badge = <ValidationBadge state={a.validation} compact={compact && a.validation === 'editorial'} />;

  return (
    <li className={`attestation${compact ? ' attestation-compact' : ''}`}>
      <span className="attestation-date mono">{date ?? 'undated'}</span>
      <div className="stack-4 min0">
        <blockquote className="attestation-quote">
          {highlightLemma(a.quote, lemma).map((p, i) => (p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>))}
        </blockquote>
        {/* Compact (word page): one line. Full (sense page): the citation, then kind, link and validation. */}
        {compact ? (
          <div className="attestation-ref">
            {kind}
            {cite}
            {link}
            {badge}
          </div>
        ) : (
          <div className="attestation-ref attestation-ref-full">
            {cite}
            <div className="attestation-ref">
              {kind}
              {link}
              {r.identifier && <span className="mono small">{r.identifier}</span>}
              {r.accessed_on && <span className="small">accessed {r.accessed_on}</span>}
              {badge}
            </div>
          </div>
        )}
      </div>
    </li>
  );
}

export function AttestationList({ items, lemma, compact = false }: { items: Attestation[]; lemma: string; compact?: boolean }) {
  return (
    <ol className="attestations">
      {items.map((a) => (
        <AttestationItem key={a.id} a={a} lemma={lemma} compact={compact} />
      ))}
    </ol>
  );
}
