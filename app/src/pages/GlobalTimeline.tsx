import { useEffect, useMemo, useRef, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Calendar, Loader2 } from 'lucide-react';
import { fetchPeriods, fetchSenseCount, fetchTimelinePage, TIMELINE_PAGE } from '../lib/api';
import { periodLabel, slug } from '../lib/format';
import { matchesFilters, useViewParams } from '../lib/params';
import { POS_ORDER } from '../lib/types';
import { FilterBar } from '../components/FilterBar';
import { LineageTable, type LineageRow } from '../components/LineageTable';
import { ShareBar } from '../components/ShareBar';
import { useCrumbs, useMainScroller } from '../components/Shell';
import { ErrorState, Loading } from '../components/States';

/** All senses across the lexicon, newest first, with year separators (US5). */
export function GlobalTimeline() {
  useCrumbs([{ label: 'Global timeline' }]);
  const [params, update] = useViewParams();
  const main = useMainScroller();
  const sentinel = useRef<HTMLDivElement>(null);
  const [jumpTo, setJumpTo] = useState<{ label: string; offset: number } | null>(null);

  const total = useQuery({ queryKey: ['senseCount'], queryFn: fetchSenseCount });
  const periods = useQuery({ queryKey: ['periods'], queryFn: fetchPeriods });
  const pages = useInfiniteQuery({
    queryKey: ['timeline'],
    queryFn: ({ pageParam }) => fetchTimelinePage(pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.length < TIMELINE_PAGE ? undefined : all.length * TIMELINE_PAGE),
  });

  const loaded = useMemo(() => pages.data?.pages.flat() ?? [], [pages.data]);

  const rows = useMemo<LineageRow[]>(() => {
    const out: LineageRow[] = [];
    let last: string | null = null;
    for (const s of loaded) {
      const p = periodLabel(s.date_earliest);
      if (p !== last) out.push({ kind: 'sep', label: (last = p) });
      out.push({ kind: 'sense', sense: s, alive: s.obsolete_year == null, matches: matchesFilters(params, s) });
    }
    return out;
  }, [loaded, params]);

  // Infinite scroll: load the next 50 when the sentinel nears the bottom of <main>.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = pages;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !main?.current) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) void fetchNextPage();
      },
      { root: main.current, rootMargin: '200px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [main, hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Jump to a period: load pages until its first sense is in, then scroll its separator into view.
  useEffect(() => {
    if (!jumpTo) return;
    if (loaded.length <= jumpTo.offset && hasNextPage) {
      if (!isFetchingNextPage) void fetchNextPage();
      return;
    }
    const target = jumpTo.label;
    setJumpTo(null);
    requestAnimationFrame(() => {
      const el = document.getElementById(`sep-${slug(target)}`);
      const m = main?.current;
      if (el && m) m.scrollTo({ top: m.scrollTop + el.getBoundingClientRect().top - m.getBoundingClientRect().top - 16 });
    });
  }, [jumpTo, loaded.length, hasNextPage, isFetchingNextPage, fetchNextPage, main]);

  return (
    <>
      <div className="card page-head">
        <h1 className="h-page">Global timeline</h1>
        <p className="muted">Registered senses across the lexicon, newest first. Lines join senses of the same lineage.</p>
      </div>
      <ShareBar title="Global timeline" citeKey="timeline" />
      <FilterBar params={params} update={update} posOptions={[...POS_ORDER]}>
        <label className="control">
          <Calendar size={15} className="icon-muted" aria-hidden="true" />
          Jump to
          <select
            className="input"
            value=""
            disabled={!periods.data}
            onChange={(e) => {
              const p = periods.data?.find((x) => x.label === e.target.value);
              if (p) setJumpTo({ label: p.label, offset: p.row_offset });
            }}
          >
            <option value="">{periods.isError ? 'Unavailable' : 'Period…'}</option>
            {periods.data?.map((p) => (
              <option key={p.label} value={p.label}>
                {p.label}
              </option>
            ))}
          </select>
          {jumpTo && <Loader2 size={14} className="spin" aria-label="Loading period" />}
        </label>
      </FilterBar>
      {pages.isPending && <Loading label="Loading timeline…" rows={6} />}
      {pages.isError && <ErrorState error={pages.error} retry={() => pages.refetch()} />}
      {pages.isSuccess && loaded.length === 0 && <div className="card state muted">No senses registered yet.</div>}
      {loaded.length > 0 && <LineageTable rows={rows} global pastDir={1} />}
      <div ref={sentinel} className="timeline-foot">
        {pages.isSuccess && (
          <span>
            Showing {loaded.length}
            {total.data != null ? ` of ${total.data}` : ''} senses
          </span>
        )}
        {hasNextPage && (
          <button className="btn" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? 'Loading…' : `Load ${TIMELINE_PAGE} more`}
          </button>
        )}
        {pages.isFetchNextPageError && <span className="fg">Could not load more. Try the button again.</span>}
      </div>
    </>
  );
}
