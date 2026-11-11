import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Shell } from './components/Shell';
import { Home } from './pages/Home';
import { SearchResults } from './pages/SearchResults';
import { WordPage } from './pages/WordPage';
import { SensePage } from './pages/SensePage';
import { Docs } from './pages/Docs';
import { About } from './pages/About';
import { Contribute } from './pages/Contribute';
import { ProposeUsage } from './pages/ProposeUsage';
import { TaxonomyPage } from './pages/TaxonomyPage';
import { SynsetPage } from './pages/SynsetPage';
import { StatsPage } from './pages/StatsPage';
import { ProposeSense } from './pages/ProposeSense';
import { ProposeRelation } from './pages/ProposeRelation';
import { ReviewQueue } from './pages/ReviewQueue';
import { Discovery } from './pages/Discovery';
import { DiscoveryWord } from './pages/DiscoveryWord';
import { NotFoundRoute } from './pages/NotFound';
import './styles/app.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Shell>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/search/:q" element={<SearchResults />} />
            <Route path="/word/:lemma" element={<WordPage />} />
            <Route path="/sense/:id" element={<SensePage />} />
            <Route path="/docs" element={<Docs />} />
            <Route path="/taxonomy" element={<TaxonomyPage />} />
            <Route path="/synset/:id" element={<SynsetPage />} />
            <Route path="/stats" element={<StatsPage />} />
            <Route path="/about" element={<About />} />
            <Route path="/contribute" element={<Contribute />} />
            <Route path="/contribute/usage" element={<ProposeUsage />} />
            <Route path="/contribute/sense" element={<ProposeSense />} />
            <Route path="/contribute/relation" element={<ProposeRelation />} />
            <Route path="/review" element={<ReviewQueue />} />
            <Route path="/discovery" element={<Discovery />} />
            <Route path="/discovery/:lemma" element={<DiscoveryWord />} />
            <Route path="*" element={<NotFoundRoute />} />
          </Routes>
        </Shell>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
