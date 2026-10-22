import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation, useMatch } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, BookOpen, ChevronRight, FileText, House, Info, ListTree, MessageSquarePlus, Monitor, Moon, PanelLeft, ShieldCheck, Sun } from 'lucide-react';
import { fetchWords } from '../lib/api';
import { useTheme, type ThemePref } from '../lib/theme';
import { useIsModerator, useSession } from '../lib/contributions';
import { SearchBox } from './SearchBox';

export interface Crumb {
  label: string;
  to?: string;
}

const CrumbsCtx = createContext<(c: Crumb[]) => void>(() => {});

/** Pages declare their breadcrumb trail; Home is always first. */
export function useCrumbs(crumbs: Crumb[]) {
  const set = useContext(CrumbsCtx);
  const key = JSON.stringify(crumbs);
  useEffect(() => set(JSON.parse(key)), [key, set]);
}

const THEME_ICON = { system: Monitor, light: Sun, dark: Moon };
const THEME_LABEL: Record<ThemePref, string> = { system: 'System', light: 'Light', dark: 'Dark' };

/** Cycles System → Light → Dark; the icon shows the current choice. */
function ThemeToggle() {
  const { pref, next, cycle } = useTheme();
  const Icon = THEME_ICON[pref];
  const label = `Theme: ${THEME_LABEL[pref]}. Switch to ${THEME_LABEL[next]}`;
  return (
    <button className="icon-btn theme-btn" aria-label={label} title={label} onClick={cycle}>
      <Icon size={17} aria-hidden="true" />
    </button>
  );
}

function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  const words = useQuery({ queryKey: ['words'], queryFn: fetchWords, staleTime: 5 * 60_000 });
  const wordMatch = useMatch('/word/:lemma');
  const current = wordMatch?.params.lemma;
  const session = useSession();
  const moderator = useIsModerator(session).data === true;

  return (
    <aside className="sidebar" aria-label="Sidebar">
      <div className="brand">
        <Link to="/" className="wordmark" onClick={onNavigate}>
          ShiftNet
        </Link>
        <div className="small muted">A WordNet browser for meaning over time</div>
      </div>
      <nav className="nav" aria-label="Main">
        <NavLink to="/" end className="nav-item" onClick={onNavigate}>
          <House size={16} aria-hidden="true" />
          Home
        </NavLink>
        <NavLink to="/taxonomy" className="nav-item" onClick={onNavigate}>
          <ListTree size={16} aria-hidden="true" />
          Taxonomy
        </NavLink>
        <NavLink to="/stats" className="nav-item" onClick={onNavigate}>
          <BarChart3 size={16} aria-hidden="true" />
          Statistics
        </NavLink>
        <NavLink to="/about" className="nav-item" onClick={onNavigate}>
          <Info size={16} aria-hidden="true" />
          About &amp; sources
        </NavLink>
        <NavLink to="/docs" className="nav-item" onClick={onNavigate}>
          <FileText size={16} aria-hidden="true" />
          Documentation
        </NavLink>
        <NavLink to="/contribute" className="nav-item" onClick={onNavigate}>
          <MessageSquarePlus size={16} aria-hidden="true" />
          Contribute
        </NavLink>
        {moderator && (
          <NavLink to="/review" className="nav-item" onClick={onNavigate}>
            <ShieldCheck size={16} aria-hidden="true" />
            Review queue
          </NavLink>
        )}
      </nav>
      <div className="sidebar-label">Lexicon</div>
      <div className="lexicon">
        {words.isPending && <div className="small muted pad-x">Loading…</div>}
        {words.isError && <div className="small muted pad-x">Lexicon unavailable</div>}
        {words.data?.map((w) => (
          <Link
            key={w.lemma}
            to={`/word/${encodeURIComponent(w.lemma)}?view=timeline`}
            className={`lexicon-item${current === w.lemma ? ' active' : ''}`}
            aria-current={current === w.lemma ? 'page' : undefined}
            onClick={onNavigate}
          >
            <ChevronRight size={13} className="icon-faint" aria-hidden="true" />
            <BookOpen size={15} className="icon-muted" aria-hidden="true" />
            <span>{w.lemma}</span>
            <span className="mono small muted">{w.sense_count}</span>
          </Link>
        ))}
      </div>
    </aside>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const loc = useLocation();
  const isHome = loc.pathname === '/';
  const [crumbs, setCrumbs] = useState<Crumb[]>([]);
  const [navOpen, setNavOpen] = useState(false);
  const mainRef = useRef<HTMLElement>(null);

  // New page: scroll to top. Same page with new params (filters, slider): keep position.
  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0 });
  }, [loc.pathname]);

  // "/" focuses search from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName ?? '').toUpperCase();
      if (e.key === '/' && !/INPUT|SELECT|TEXTAREA/.test(tag)) {
        e.preventDefault();
        document.querySelector<HTMLInputElement>('[data-search-input]')?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const trail: Crumb[] = [{ label: 'Home', to: '/' }, ...crumbs];

  return (
    <CrumbsCtx.Provider value={setCrumbs}>
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <div className={`shell${navOpen ? ' nav-open' : ''}`}>
          <Sidebar onNavigate={() => setNavOpen(false)} />
          {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />}
          <div className="content">
            <header className="topbar">
              <button
                className="icon-btn nav-btn"
                aria-label={navOpen ? 'Close sidebar' : 'Open sidebar'}
                aria-expanded={navOpen}
                onClick={() => setNavOpen((o) => !o)}
              >
                <PanelLeft size={18} aria-hidden="true" />
              </button>
              <div className="topbar-search">
                {!isHome && <SearchBox size="sm" placeholder="Search words… (Press /)" />}
              </div>
              <ThemeToggle />
            </header>
            <nav className="crumbs" aria-label="Breadcrumb">
              {trail.map((c, i) => {
                const last = i === trail.length - 1;
                return (
                  <span key={i} className="crumb">
                    {last || !c.to ? (
                      <span className={last ? 'fg' : 'fg2'} aria-current={last ? 'page' : undefined}>
                        {c.label}
                      </span>
                    ) : (
                      <Link to={c.to}>{c.label}</Link>
                    )}
                    {!last && <ChevronRight size={13} className="icon-faint" aria-hidden="true" />}
                  </span>
                );
              })}
            </nav>
            <main id="main" ref={mainRef} className="main" tabIndex={-1}>
              <div className="page">{children}</div>
            </main>
          </div>
        </div>
    </CrumbsCtx.Provider>
  );
}
