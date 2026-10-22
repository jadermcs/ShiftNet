import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Copy, Link2, Quote } from 'lucide-react';
import { citations } from '../lib/cite';

function useCopy() {
  const [copied, setCopied] = useState<string | null>(null);
  const t = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(t.current), []);
  const copy = (text: string, key: string) => {
    navigator.clipboard?.writeText(text).catch(() => {});
    setCopied(key);
    clearTimeout(t.current);
    t.current = setTimeout(() => setCopied(null), 1600);
  };
  return [copied, copy] as const;
}

/** Stable link + Cite (US10). The URL carries view, filters and date, so it restores the same state. */
export function ShareBar({ title, citeKey }: { title: string; citeKey: string }) {
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  const [copied, copy] = useCopy();
  const url = `${window.location.origin}${loc.pathname}${loc.search}`;
  const { apa, bibtex } = citations(title, citeKey, url);

  useEffect(() => setOpen(false), [loc.pathname]);

  return (
    <>
      <div className="sharebar">
        <span className="sharebar-url mono">
          <Link2 size={14} aria-hidden="true" />
          {url.replace(/^https?:\/\//, '')}
        </span>
        <div className="row-gap">
          <button className="btn" onClick={() => copy(url, 'link')}>
            <Copy size={14} aria-hidden="true" />
            {copied === 'link' ? 'Copied' : 'Copy link'}
          </button>
          <button className="btn btn-primary" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            <Quote size={14} aria-hidden="true" />
            Cite
          </button>
        </div>
      </div>
      <span className="sr-only" aria-live="polite">{copied ? 'Copied to clipboard' : ''}</span>
      {open && (
        <div className="card cite">
          <div className="cite-block">
            <div className="cite-head">
              <span className="label">APA</span>
              <button className="btn btn-sm" onClick={() => copy(apa, 'apa')}>
                <Copy size={13} aria-hidden="true" />
                {copied === 'apa' ? 'Copied' : 'Copy'}
              </button>
            </div>
            <div className="cite-text">{apa}</div>
          </div>
          <div className="cite-block">
            <div className="cite-head">
              <span className="label">BibTeX</span>
              <button className="btn btn-sm" onClick={() => copy(bibtex, 'bib')}>
                <Copy size={13} aria-hidden="true" />
                {copied === 'bib' ? 'Copied' : 'Copy'}
              </button>
            </div>
            <pre className="cite-text mono">{bibtex}</pre>
          </div>
        </div>
      )}
    </>
  );
}
