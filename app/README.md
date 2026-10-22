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

   For local testing of contributions you can also run `psql "$DATABASE_URL" -f supabase/seed/contributions_seed.sql` (demo accounts and contributions, once after a reset). It is kept out of `seed.sql` on purpose: don't load it into a hosted project.

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

| `contributions` | Proposals from signed-in contributors: `kind` (`usage` or `sense`), `status` (`pending`, `accepted`, `rejected`), the normalised `payload`, the `checks` it got, `validation` once accepted (`automatic` or `manual`), `reviewer_id`, `review_note`, and links to what was published (`sense_id`, `attestation_id`). A contributor reads only their own rows, a moderator all; nobody writes them except through the RPCs below. |
| `moderators` | Who may review (`user_id` → `auth.users`). Added by the ShiftNet team with a privileged connection; a user can only see their own row. |

RPCs: `search_lemmas` (suggestions, case/accent-insensitive), `close_spellings`, `resolve_lemma`, `timeline_periods`. Signed-in only: `check_usage`, `check_sense`, `submit_usage`, `submit_sense`, `review_contribution`, `is_moderator` (see below).

The lexicon tables are read-only for `anon` / `authenticated` (RLS select policies, explicit grants). The ShiftNet team loads data with a privileged connection, e.g. by editing `supabase/seed/generate_seed.py` and running `npm run seed:generate`; contributors add to it only through the contribution RPCs.

## Contributions & validation

Anyone with an email address can propose a **usage** (a dated quotation for an existing sense, with its reference) or a **sense** (lemma, part of speech, gloss, examples, date as recorded and earliest year, shift type, parent senses, date source, and ideally a supporting usage). Proposals go to `security definer` functions in `supabase/migrations/20261022140000_contributions.sql`; the checks run in Postgres, so the client cannot skip them, and the stored payload is the server's normalised copy (known keys only, whitespace collapsed, existing head words keep their spelling).

Every check gives one of four results. **Error**: the submission is refused and nothing is stored; the form shows the messages next to the fields. **Review**: stored as pending for a moderator. **Note**: shown, no effect. **Pass**: recorded so contributors and moderators see what was checked. `check_usage` / `check_sense` run the same checks without submitting (the form's *Run checks* button).

| Check | Applies to | Result when it fails |
| --- | --- | --- |
| Signed in with an email account (anonymous sessions refused) | all | error |
| Rate limit: 20 submissions per 24 h, 10 pending per contributor | all | error |
| Required fields and length bounds (quote 15–1,200 chars, gloss 10–300, title ≤ 300, ≤ 5 examples of ≤ 200 …); enum values valid | all | error |
| Years are whole years between 600 and this year; access date real and not in the future | all | error |
| URL is a full `http(s)://host.tld/…` address; a website reference has one | reference | error |
| Target sense exists; same quote not already attested or proposed for it | usage | error |
| Parent senses exist (≤ 4); `root` has no parent, any other shift has at least one | sense | error |
| Gloss not identical to an existing or pending sense of the same word and POS | sense | error |
| Quote contains the lemma, a synset member or a plausible inflection (prefix at a word start, final -e/-y dropped: *nicer*, *clouded*, *trolling*) | usage | review |
| Year of use not before the sense's `date_earliest` (otherwise a possible antedating) and not after `obsolete_year` | usage | review |
| Quote has no markup or links | usage | review |
| Reference has a URL or an identifier; ISBN checksum valid; DOI well formed; use not dated after the work's publication year | reference | review |
| Gloss not too close (trigram similarity ≥ 0.5) to an existing sense; word already a head word; parents older than the new sense | sense | review |
| A supporting usage is given, and it passes the usage checks | sense | review |
| Contributor trusted: 3 or more accepted contributions and none rejected | sense | review |
| Website reference has an access date; parent from another word | — | note |

**Outcome.** No error and no review flag: published at once (`sources` row reused when the URL, else the identifier, else kind + title + author match; `attestations` row, and for a sense `senses` + `sense_parents` + `sense_lemmas` with the next free id such as `cloud.n.07`), with `validation = 'automatic'`. Otherwise the contribution waits as `pending` and is not part of the lexicon. So usages are auto-accepted when clean; new senses only from trusted contributors.

**Moderation** (`/review`, `review_contribution(id, 'accept' | 'reject', note)`): accepting a pending contribution re-runs the blocking checks (the lexicon may have changed) and publishes it with `validation = 'manual'`; rejecting needs a note, which the contributor sees. Auto-accepted contributions are listed too: *Confirm* turns them into `manual`, *Withdraw* removes the published rows (a sense others now depend on cannot be withdrawn here). Moderators cannot review their own contributions. Link liveness is not checked: it would need an Edge Function, and auto-accept does not depend on it.

**In the interface** every validation state uses `ValidationBadge`: *Editorial*, *Auto-checked*, *Reviewed*, *Pending review*, *Rejected*. Pending usages appear on a sense page only for their contributor and moderators, in a dashed box under the attestations, labelled pending.

**Auth.** Contributors sign in with Supabase Auth email OTP: one email carries a magic link (PKCE) and a 6-digit code, so it also works when the email is opened on another device. No passwords to store, and an email identity makes the per-contributor rate limit and trust rule meaningful, which anonymous sign-ins would not. Sessions persist in local storage. In the dashboard: enable the Email provider, add the site URL and `http://localhost:5173` to the redirect URLs with a `/**` wildcard (the link returns to the page where sign-in started), and include `{{ .Token }}` in the Magic Link email template so the code is sent. Make someone a moderator with:

```sql
insert into public.moderators (user_id) select id from auth.users where email = 'you@example.org';
```

`supabase/seed/contributions_seed.sql` adds demo contributions (one auto-accepted, two pending, one rejected) from two demo accounts that cannot sign in; run it once after `seed.sql`.

| Route | Page |
| --- | --- |
| `/contribute` | Sign in, your contributions with their state and moderator notes, what the badges mean |
| `/contribute/usage?sense=<id>` | Propose a usage (sense picker when no `sense`) |
| `/contribute/sense?lemma=<word>` | Propose a sense |
| `/review` | Moderator queue: needs review, auto-accepted, reviewed |

## Where the PRD lives in the code

| Story | Code |
| --- | --- |
| US1 Home | `src/pages/Home.tsx` |
| US2 Search | `src/components/SearchBox.tsx`, `src/pages/SearchResults.tsx` |
| US3 Word entry | `src/pages/WordPage.tsx` (`SensesView`) |
| US4 Lineage | `src/lib/graph.ts` (layout), `src/components/LineageTable.tsx`, `LineageGraph.tsx` |
| Documentation (replaces US5 Global timeline) | `src/pages/Docs.tsx` (`/docs`: website, backend tools, MCP server) |
| US6 / US7 Sense detail, relations | `src/pages/SensePage.tsx` |
| US8 Time travel | `TimelineView` in `WordPage.tsx` (`?at=`) |
| US9 Filters | `src/components/FilterBar.tsx`, `src/lib/params.ts` |
| US10 Share & cite | `src/components/ShareBar.tsx`, `src/lib/cite.ts`; all view state is in the URL |
| Attestations | `src/components/Attestations.tsx`, `src/lib/reference.ts`; top 3 in `SensesView` (`WordPage.tsx`), all in `SensePage.tsx` (`#attestations`) |
| Validation state | `src/components/ValidationBadge.tsx` |
| Contributions | `src/lib/contributions.ts` (types, RPC calls, session), `src/pages/Contribute.tsx`, `ProposeUsage.tsx`, `ProposeSense.tsx`, `ReviewQueue.tsx`; forms in `src/components/UsageFields.tsx`, `ReferenceFields.tsx`, `Field.tsx`, `SubmitBar.tsx`, `ChecksList.tsx`; `ContributionCard.tsx`, `SignIn.tsx`, `ContributeLinks.tsx` (entry points on word and sense pages) |
