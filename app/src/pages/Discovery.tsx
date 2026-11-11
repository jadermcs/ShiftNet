import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { BookOpen, ChevronLeft, ChevronRight, Search } from 'lucide-react';
import { fetchDiscoveredWords, PAGE_SIZE, type WordFilter, type WordSort } from '../lib/discovery';
import { useCrumbs } from '../components/Shell';
import { Empty, ErrorState, Loading } from '../components/States';

const SORTS: { id: WordSort; label: string }[] = [
  { id: 'frequent', label: 'Most frequent' },
  { id: 'alpha', label: 'A–Z' },
  { id: 'candidates', label: 'Most candidates' },
];

const year = (d: string | null) => (d ? d.slice(0, 4) : '?');

/** Every word sense discovery has run on, with its candidate senses waiting for review. */
export function Discovery() {
  useCrumbs([{ label: 'Discovery' }]);
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const status = (params.get('status') as WordFilter) === 'all' ? 'all' : 'pending';
  const sort = (SORTS.find((s) => s.id === params.get('sort'))?.id ?? 'frequent') as WordSort;
  const page = Math.max(0, Number(params.get('page') ?? 0) || 0);
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);

  const set = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null || v === '') p.delete(k);
      else p.set(k, v);
    }
    if (!('page' in next)) p.delete('page');
    setParams(p, { replace: true });
  };

  // Search as you type, a moment after the last key.
  useEffect(() => {
    if (draft === q) return;
    const t = setTimeout(() => set({ q: draft.trim() || null }), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  const words = useQuery({
    queryKey: ['discovery-words', q, status, sort, page],
    queryFn: () => fetchDiscoveredWords(q, status, sort, page),
    placeholderData: keepPreviousData,
  });
  const d = words.data;
  const from = page * PAGE_SIZE;

  return (
    <>
      <div className="card page-head">
        <span className="label">Sense discovery</span>
        <h1 className="h-page">Discovered senses</h1>
        <p className="muted">
          Candidate senses found by clustering each word’s usages in the fineweb-edu web corpus (crawls from 2013 to 2025).
          A candidate is a group of sentences that use the word the same way, described by its strongest terms. It is not
          part of the lexicon until it is reviewed: matched to an existing sense, promoted to a new one, or rejected.
        </p>
        {d && (
          <p className="small fg2">
            {d.total_words.toLocaleString()} words, {d.pending_words.toLocaleString()} with candidates waiting for review.
          </p>
        )}
      </div>

      <div className="discovery-controls">
        <label className="search search-sm discovery-search">
          <Search size={14} className="search-icon" aria-hidden="true" />
          <span className="sr-only">Find a word</span>
          <input
            className="input"
            type="search"
            placeholder="Find a word…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && set({ q: draft.trim() || null })}
          />
        </label>
        <div role="radiogroup" aria-label="Show" className="segmented segmented-sm">
          {(['pending', 'all'] as const).map((s) => (
            <button key={s} role="radio" aria-checked={status === s} onClick={() => set({ status: s === 'pending' ? null : s })}>
              {s === 'pending' ? 'To review' : 'All'}
            </button>
          ))}
        </div>
        <label className="control">
          Sort
          <select className="input input-sm" value={sort} onChange={(e) => set({ sort: e.target.value === 'frequent' ? null : e.target.value })}>
            {SORTS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {words.isPending && <Loading label="Loading words…" rows={4} />}
      {words.isError && <ErrorState error={words.error} retry={() => words.refetch()} />}
      {d && d.matches === 0 && <Empty>No discovered word matches “{q}”.</Empty>}
      {d && d.matches > 0 && (
        <section className="card table-scroll" aria-label="Discovered words">
          <table className="discovery-table">
            <thead>
              <tr>
                <th scope="col" className="right">Rank</th>
                <th scope="col">Word</th>
                <th scope="col" className="right">To review</th>
                <th scope="col" className="right">Candidates</th>
                <th scope="col" className="right">Usages</th>
                <th scope="col">Crawls</th>
                <th scope="col"><span className="sr-only">Lexicon</span></th>
              </tr>
            </thead>
            <tbody>
              {d.words.map((w) => (
                <tr key={w.lemma}>
                  <td className="right mono small muted">{w.rank.toLocaleString()}</td>
                  <td>
                    <Link to={`/discovery/${encodeURIComponent(w.lemma)}`} className="discovery-word">
                      {w.lemma}
                    </Link>
                  </td>
                  <td className="right mono">{w.pending || <span className="muted">–</span>}</td>
                  <td className="right mono">{w.candidates}</td>
                  <td className="right mono small fg2">{w.usages.toLocaleString()}</td>
                  <td className="mono small muted">
                    {year(w.first_seen)}–{year(w.last_seen)}
                  </td>
                  <td>
                    {w.in_lexicon && (
                      <Link to={`/word/${encodeURIComponent(w.lemma)}`} className="chip chip-sm" title="Open the word in the lexicon">
                        <BookOpen size={11} aria-hidden="true" className="inline-icon" /> in lexicon
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {d && d.matches > PAGE_SIZE && (
        <nav className="pager" aria-label="Pages">
          <button className="btn btn-sm" disabled={page === 0} onClick={() => set({ page: page - 1 ? String(page - 1) : null })}>
            <ChevronLeft size={14} aria-hidden="true" />
            Previous
          </button>
          <span className="small muted mono">
            {(from + 1).toLocaleString()}–{Math.min(from + PAGE_SIZE, d.matches).toLocaleString()} of {d.matches.toLocaleString()}
          </span>
          <button className="btn btn-sm" disabled={from + PAGE_SIZE >= d.matches} onClick={() => set({ page: String(page + 1) })}>
            Next
            <ChevronRight size={14} aria-hidden="true" />
          </button>
        </nav>
      )}
    </>
  );
}
