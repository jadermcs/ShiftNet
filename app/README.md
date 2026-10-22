# ShiftNet app

React + Supabase implementation of the ShiftNet PRD (`../PRD_ShiftNet.pdf`), built to the design system (`../styles.css`, `../tokens/`) and the prototype (`../ShiftNet.dc.html`).

Stack: Vite, React 18, TypeScript, React Router, TanStack Query, supabase-js, lucide-react.

## Setup

1. Create the database. With the Supabase CLI (needs Docker for local):

   ```sh
   supabase init          # once; keeps the existing supabase/migrations and supabase/seed.sql
   supabase start         # local stack; applies migrations and seed.sql
   # or, for a hosted project:
   supabase link --project-ref <ref>
   supabase db push
   psql "$DATABASE_URL" -f supabase/seed.sql   # sample lexicon
   ```

   Without the CLI, run `supabase/migrations/*.sql` and then `supabase/seed.sql` in the dashboard's SQL editor.

2. Configure the client:

   ```sh
   cp .env.example .env   # set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY
   ```

   Use the publishable (or legacy anon) key, never the secret / service_role key.

3. Run:

   ```sh
   npm install
   npm run dev
   ```

`npm run build` type-checks and builds to `dist/`. Routes are client-side (`/word/cloud`, `/sense/cloud.n.02`), so the host must serve `index.html` for unknown paths; `public/_redirects` (Netlify) and `vercel.json` do that.

`npm test` runs the unit tests (lineage layout, URL state, quote highlighting and references).

## Data model

| Table | Purpose |
| --- | --- |
| `senses` | One row per sense: lemma, POS, gloss, examples, date as recorded (`date_label`) and earliest year for sorting (`date_earliest`), obsolescence, shift type, date source. `sense_num` (n. 2) and `branch` (A–H colour) are kept up to date by a trigger, in registration order. |
| `sense_parents` | Parent links. `position 0` is the branch a sense grows from; higher positions are merged parents. Each link has its own `source`. |
| `sense_lemmas` | Synset members, including multi-word expressions ("cloud computing"), used for synonyms and search. |
| `relations` | Hypernyms, hyponyms, antonyms, meronyms, holonyms, derived forms (by target lemma). |
| `words` (view) | One row per head word, for the sidebar. |
| `sources` | Cited works an attestation points to: `kind` (book, website, article, journal, newspaper, dictionary, corpus, archive, other), title, author, publisher or site, date, URL, ISBN/DOI, access date. |
| `attestations` | Dated quotations showing a sense in use: `quote`, `year` / `date_label`, `locator` (page, chapter, act and scene), `source_id`, and `validation` (`editorial`, `automatic`, `manual`; senses carry the same column). `relevance` (0–1) is kept up to date by a trigger from `attestation_relevance()`, or set by hand with `relevance_override`. |
| `ranked_attestations` (view) | Attestations in display order per sense (`rank` from 1, `total`), with the source inlined. A work's second quotation ranks after every other work's best one, so the top 3 come from different works where possible. |

**Attestation relevance** adds up: the quote contains the head word or an inflection (0.3); checked by the team or a moderator (0.2) vs. automatically (0.1); kind of source (book, journal, dictionary 0.15 … website 0.07); dated (0.1); readable length, 40–200 characters (0.15); early evidence, within 50 years of the sense's registration (0.1). Word pages show each sense's top 3; the sense page lists all of them, by relevance or oldest first.

RPCs: `search_lemmas` (suggestions, case/accent-insensitive), `close_spellings`, `resolve_lemma`, `timeline_periods`.

Everything is read-only for `anon` / `authenticated` (RLS select policies, explicit grants). Loading data is done by the ShiftNet team with a privileged connection, e.g. by editing `supabase/seed/generate_seed.py` and running `npm run seed:generate`.

## Where the PRD lives in the code

| Story | Code |
| --- | --- |
| US1 Home | `src/pages/Home.tsx` |
| US2 Search | `src/components/SearchBox.tsx`, `src/pages/SearchResults.tsx` |
| US3 Word entry | `src/pages/WordPage.tsx` (`SensesView`) |
| US4 Lineage | `src/lib/graph.ts` (layout), `src/components/LineageTable.tsx`, `LineageGraph.tsx` |
| US5 Global timeline | `src/pages/GlobalTimeline.tsx` (50 rows per page, infinite scroll, jump to period) |
| US6 / US7 Sense detail, relations | `src/pages/SensePage.tsx` |
| US8 Time travel | `TimelineView` in `WordPage.tsx` (`?at=`) |
| US9 Filters | `src/components/FilterBar.tsx`, `src/lib/params.ts` |
| US10 Share & cite | `src/components/ShareBar.tsx`, `src/lib/cite.ts`; all view state is in the URL |
| Attestations | `src/components/Attestations.tsx`, `src/lib/reference.ts`; top 3 in `SensesView` (`WordPage.tsx`), all in `SensePage.tsx` (`#attestations`) |
| Validation state | `src/components/ValidationBadge.tsx` |
