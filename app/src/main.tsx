import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { supabaseConfigured } from './lib/supabase';
import { Shell } from './components/Shell';
import { Home } from './pages/Home';
import { SearchResults } from './pages/SearchResults';
import { WordPage } from './pages/WordPage';
import { SensePage } from './pages/SensePage';
import { GlobalTimeline } from './pages/GlobalTimeline';
import { About } from './pages/About';
import { Contribute } from './pages/Contribute';
import { ProposeUsage } from './pages/ProposeUsage';
import { ProposeSense } from './pages/ProposeSense';
import { ReviewQueue } from './pages/ReviewQueue';
import { NotFoundRoute } from './pages/NotFound';
import './styles/app.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false } },
});

function MissingConfig() {
  return (
    <div className="card notfound" role="alert">
      <span className="label">Setup needed</span>
      <h1 className="h-page">Supabase is not configured</h1>
      <p className="muted">
        Copy <span className="mono">.env.example</span> to <span className="mono">.env</span>, set{' '}
        <span className="mono">VITE_SUPABASE_URL</span> and <span className="mono">VITE_SUPABASE_PUBLISHABLE_KEY</span>,
        then restart the dev server.
      </p>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Shell>
          {supabaseConfigured ? (
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/search/:q" element={<SearchResults />} />
              <Route path="/word/:lemma" element={<WordPage />} />
              <Route path="/sense/:id" element={<SensePage />} />
              <Route path="/timeline" element={<GlobalTimeline />} />
              <Route path="/about" element={<About />} />
              <Route path="/contribute" element={<Contribute />} />
              <Route path="/contribute/usage" element={<ProposeUsage />} />
              <Route path="/contribute/sense" element={<ProposeSense />} />
              <Route path="/review" element={<ReviewQueue />} />
              <Route path="*" element={<NotFoundRoute />} />
            </Routes>
          ) : (
            <MissingConfig />
          )}
        </Shell>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
