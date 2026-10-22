import { useEffect, useId, useState, type KeyboardEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Loader2, Search } from 'lucide-react';
import { closeSpellings, resolveLemma, searchLemmas } from '../lib/api';
import { normalize } from '../lib/format';
import type { CloseSpelling, Suggestion } from '../lib/types';

export const hrefFor = (s: Pick<CloseSpelling, 'kind' | 'lemma' | 'sense_id'>) =>
  s.kind === 'sense' && s.sense_id ? `/sense/${s.sense_id}` : `/word/${encodeURIComponent(s.lemma)}`;

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

interface Props {
  size: 'lg' | 'sm';
  autoFocus?: boolean;
  placeholder: string;
}

/** Search with suggestions after 2 characters (US2). Arrow keys move, Enter opens, Escape closes. */
export function SearchBox({ size, autoFocus, placeholder }: Props) {
  const navigate = useNavigate();
  const listId = useId();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const dq = useDebounced(q, 120);
  const ready = normalize(dq).length >= 2;

  const sugg = useQuery({ queryKey: ['suggest', normalize(dq)], queryFn: () => searchLemmas(dq), enabled: ready });
  const items: Suggestion[] = ready ? (sugg.data ?? []) : [];
  const empty = ready && sugg.isSuccess && items.length === 0;
  const close = useQuery({ queryKey: ['close', normalize(dq)], queryFn: () => closeSpellings(dq), enabled: empty });

  const go = (href: string) => {
    setQ('');
    setOpen(false);
    setActive(-1);
    navigate(href);
  };

  const submit = async () => {
    const text = q.trim();
    if (!text) return;
    if (active >= 0 && items[active]) return go(hrefFor(items[active]));
    setOpen(false);
    try {
      const exact = await resolveLemma(text);
      go(exact ? hrefFor(exact) : `/search/${encodeURIComponent(text)}`);
    } catch {
      go(`/search/${encodeURIComponent(text)}`);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.min(a + 1, items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, -1));
    } else if (e.key === 'Escape') {
      setOpen(false);
      e.currentTarget.blur();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      void submit();
    }
  };

  const showList = open && normalize(q).length >= 2;

  return (
    <div className={`search search-${size}`}>
      <Search className="search-icon" size={size === 'lg' ? 18 : 15} aria-hidden="true" />
      <input
        data-search-input
        autoFocus={autoFocus}
        value={q}
        placeholder={placeholder}
        aria-label="Search words"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
        onChange={(e) => {
          setQ(e.target.value);
          setActive(-1);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKey}
      />
      {sugg.isFetching && <Loader2 className="search-spin spin" size={15} aria-hidden="true" />}
      {showList && (
        <div className="popover" id={listId} role="listbox" aria-label="Suggestions">
          {sugg.isError && <div className="popover-note">Search is unavailable. Try again in a moment.</div>}
          {!ready || (sugg.isPending && !sugg.data) ? (
            <div className="popover-note muted">Searching…</div>
          ) : null}
          {items.map((s, i) => (
            <button
              key={`${s.kind}:${s.lemma}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={`suggestion${i === active ? ' active' : ''}`}
              onMouseDown={(e) => {
                e.preventDefault();
                go(hrefFor(s));
              }}
              tabIndex={-1}
            >
              <span>
                <span className="suggestion-lemma">{s.lemma}</span> <em className="muted">{s.pos}</em>
              </span>
              <span className="mono small muted">{s.meta}</span>
            </button>
          ))}
          {empty && (
            <div className="popover-note">
              <span>No results</span>
              <div className="close-row">
                Close spellings:
                {close.isPending && <span className="muted">…</span>}
                {close.data?.length === 0 && <span className="muted">none found</span>}
                {close.data?.map((c) => (
                  <button
                    key={c.lemma}
                    className="pill"
                    tabIndex={-1}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      go(hrefFor(c));
                    }}
                  >
                    {c.lemma}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
