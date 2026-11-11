# ShiftNet app

React implementation of the ShiftNet PRD (`../PRD_ShiftNet.pdf`), built to the design system (`../styles.css`, `../tokens/`) and the prototype (`../ShiftNet.dc.html`). It runs locally against the backend's API and SQLite database.

Stack: Vite, React 18, TypeScript, React Router, TanStack Query, lucide-react; the backend (`../backend`) serves the data.

## Setup

ShiftNet runs locally. The data lives in one SQLite file owned by the backend (`../backend`), and the app reads and writes it through the backend's API.

1. Start the API (see `../backend/README.md`; the database is `$SHIFTNET_DB`, by default `~/data/shiftnet.sqlite`):

   ```sh
   cd ../backend
   uv sync
   uv run shiftnet seed     # once, for an empty database: the sample lexicon
   uv run shiftnet serve    # http://127.0.0.1:8000/api/…
   ```

2. Run the app; the dev server proxies `/api` to the backend (`SHIFTNET_API` overrides the address):

   ```sh
   bun install
   bun run dev
   ```

For a single process, build the app and let the backend serve it: `bun run build`, then `uv run shiftnet serve --static ../app/dist` and open http://127.0.0.1:8000.

`bun run build` type-checks and builds to `dist/`. `bun run test` runs the unit tests (lineage layout, URL state, quote highlighting and references).

## Data model

The schema is `../backend/src/shiftnet_backend/schema.sql`; the API is `../backend/src/shiftnet_backend/api.py`.

| Table | Purpose |
| --- | --- |
| `senses` | One row per sense: lemma, POS, gloss, examples, date as recorded (`date_label`) and earliest year for sorting (`date_earliest`), obsolescence, shift type, date source. `sense_num` (n. 2) and `branch` (A–H colour) are kept up to date by the backend (`db.renumber_senses`), in registration order. |
| `sense_parents` | Parent links. `position 0` is the branch a sense grows from; higher positions are merged parents. Each link has its own `source`. |
| `sense_lemmas` | Synset members, including multi-word expressions ("cloud computing"), used for synonyms and search. |
| `relations` | Hypernyms, hyponyms, antonyms, meronyms, holonyms, derived forms (by target lemma). |
| `sources` | Cited works an attestation points to: `kind` (book, website, article, journal, newspaper, dictionary, corpus, archive, other), title, author, publisher or site, date, URL, ISBN/DOI, access date. |
| `attestations` | Dated quotations showing a sense in use: `quote`, `year` / `date_label`, `locator` (page, chapter, act and scene), `source_id`, and `validation` (`editorial`, `automatic`, `manual`; senses carry the same column). `relevance` (0–1) is kept up to date by the backend (`db.refresh_relevance`), or set by hand with `relevance_override`. |
| ranked attestations (`api.ranked_attestations`) | Attestations in display order per sense (`rank` from 1, `total`), with the source inlined. A work's second quotation ranks after every other work's best one, so the top 3 come from different works where possible. |

**Attestation relevance** adds up: the quote contains the head word or an inflection (0.3); checked by the team or a moderator (0.2) vs. automatically (0.1); kind of source (book, journal, dictionary 0.15 … website 0.07); dated (0.1); readable length, 40–200 characters (0.15); early evidence, within 50 years of the sense's registration (0.1). Word pages show each sense's top 3; the sense page lists all of them, by relevance or oldest first.

| `contributions` | Proposals: `kind` (`usage`, `sense` or `relation`), `status` (`pending`, `accepted`, `rejected`), the normalised `payload`, the `checks` it got, `validation` once accepted (`automatic` or `manual`), `review_note`, and links to what was published (`sense_id`, `attestation_id`, or `published` for a relation). |

## Contributions & validation

There is one local user, who both contributes and reviews. They can propose a **usage** (a dated quotation for an existing sense, with its reference), a **sense** (lemma, part of speech, gloss, examples, date as recorded and earliest year, shift type, parent senses, date source, and ideally a supporting usage) or a **relation**. Proposals go to the backend (`../backend/src/shiftnet_backend/contributions.py`), which runs the checks and stores its own normalised copy of the payload (known keys only, whitespace collapsed, existing head words keep their spelling).

Every check gives one of four results. **Error**: the submission is refused and nothing is stored; the form shows the messages next to the fields. **Review**: stored as pending, for the review queue. **Note**: shown, no effect. **Pass**: recorded so the forms show what was checked. `POST /api/contributions/check/<kind>` runs the same checks without submitting (the form's *Run checks* button).

| Check | Applies to | Result when it fails |
| --- | --- | --- |
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
| Website reference has an access date; parent from another word | — | note |

**Outcome.** No error and no review flag: published at once (`sources` row reused when the URL, else the identifier, else kind + title + author match; `attestations` row, and for a sense `senses` + `sense_parents` + `sense_lemmas` with the next free id such as `cloud.n.07`), with `validation = 'automatic'`. Otherwise the contribution waits as `pending` and is not part of the lexicon. 

**Review** (`/review`, `POST /api/contributions/<id>/review` with `accept` or `reject` and a note): accepting a pending contribution re-runs the blocking checks (the lexicon may have changed) and publishes it with `validation = 'manual'`; rejecting needs a note, kept with it. Auto-accepted contributions are listed too: *Confirm* turns them into `manual`, *Withdraw* removes the published rows (a sense others now depend on cannot be withdrawn here). Link liveness is not checked.

**In the interface** every validation state uses `ValidationBadge`: *Editorial*, *Auto-checked*, *Reviewed*, *Pending review*, *Rejected*. Pending usages appear on their sense's page in a dashed box under the attestations, labelled pending.

| Route | Page |
| --- | --- |
| `/contribute` | Your contributions with their state and review notes, what the badges mean |
| `/contribute/usage?sense=<id>` | Propose a usage (sense picker when no `sense`) |
| `/contribute/sense?lemma=<word>` | Propose a sense |
| `/contribute/relation?sense=<id>` | Propose a relation |
| `/review` | Review queue: needs review, auto-accepted, reviewed |
| `/discovery` | Discovered words (sense discovery over fineweb-edu): search, filter, sort by corpus frequency |
| `/discovery/<word>` | A word's candidate senses: terms, usages per crawl year, typical and borderline usages, closest lexicon sense; match, promote or reject |

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
| Contributions | `src/lib/contributions.ts` (types, API calls), `src/lib/http.ts`, `src/pages/Contribute.tsx`, `ProposeUsage.tsx`, `ProposeSense.tsx`, `ReviewQueue.tsx`; forms in `src/components/UsageFields.tsx`, `ReferenceFields.tsx`, `Field.tsx`, `SubmitBar.tsx`, `ChecksList.tsx`; `ContributionCard.tsx`, `ContributeLinks.tsx` (entry points on word and sense pages) |
