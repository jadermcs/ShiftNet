import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useCrumbs } from '../components/Shell';

type Entry = [ReactNode, ReactNode];

const C = ({ children }: { children: ReactNode }) => <code className="mono">{children}</code>;

function Terms({ items }: { items: Entry[] }) {
  return (
    <dl className="shift-list doc-terms">
      {items.map(([k, v], i) => (
        <div key={i}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

const Code = ({ children }: { children: string }) => <pre className="cite-text">{children.trim()}</pre>;

const PAGES: Entry[] = [
  [<Link to="/">Home</Link>, 'Search box, a few words to try, and the latest registered senses.'],
  [
    <C>/search/:q</C>,
    'Head words and multi-word expressions matching a query. Search ignores case and accents and suggests close spellings when nothing matches.',
  ],
  [
    <C>/word/:lemma</C>,
    <>
      A word’s entry. <em>Senses</em> lists its senses by part of speech with their top 3 attestations. <em>Timeline</em>{' '}
      orders them by registration date and draws the lineage graph: each sense is a row, and lines join it to the sense it
      grew out of.
    </>,
  ],
  [
    <C>/sense/:id</C>,
    'One sense (e.g. cloud.n.02): gloss, examples, date and its source, parents and children, synonyms, WordNet relations, and every attestation, ordered by relevance or oldest first.',
  ],
  [<Link to="/taxonomy">Taxonomy</Link>, 'WordNet from the top down along hypernym links; hyponyms are listed by the date their oldest sense was registered.'],
  [<C>/synset/:id</C>, 'One taxonomy node: its members, path to the top, other hypernyms and hyponyms.'],
  [<Link to="/stats">Statistics</Link>, 'Figures across the lexicon: new senses per period and shift type, parts of speech, change along main parent links.'],
  [<Link to="/about">About &amp; sources</Link>, 'Data sources, how dates are assigned, shift types and how to cite.'],
  [<Link to="/contribute">Contribute</Link>, 'Propose usages, senses and relations, review them, and follow your contributions.'],
  [<C>/review</C>, 'Moderators only: the review queue.'],
];

const PARAMS: Entry[] = [
  [<C>view=timeline</C>, 'Open a word on its Timeline tab (default: senses).'],
  [<C>order=desc</C>, 'Newest sense first on the timeline (default: oldest first).'],
  [<C>at=1600</C>, 'Time travel: show the word as it stood in that year. Later senses are hidden, obsolete ones drawn hollow.'],
  [<C>pos=noun,verb</C>, 'Only these parts of speech.'],
  [<C>shift=metaphor,narrowing</C>, 'Only these shift types (root included).'],
  [<C>from=1500&amp;to=1900</C>, 'Only senses registered in this range of years.'],
];

const CONTRIB: Entry[] = [
  [
    'Usage',
    <>
      A dated quotation for an existing sense, with its reference (book, website, article …).{' '}
      <C>/contribute/usage?sense=cloud.n.02</C>
    </>,
  ],
  [
    'Sense',
    <>
      A missing sense: gloss, part of speech, examples, date as recorded and earliest year, shift type, parent senses, date
      source, and ideally a supporting usage. <C>/contribute/sense?lemma=cloud</C>
    </>,
  ],
  [
    'Relation',
    'A synonym, hypernym, hyponym, meronym or holonym for a sense. The form shows the relations the backend suggested for it.',
  ],
];

const CLI: Entry[] = [
  [<C>shiftnet serve [--static ../app/dist]</C>, 'Run the API this website talks to; with --static, also serve the built website.'],
  [<C>shiftnet seed</C>, 'Load the sample lexicon into an empty database.'],
  [<C>shiftnet import FILE [--dry-run]</C>, 'Insert or update senses from JSON lines, with parents, synonyms, relations and attestations, in one transaction.'],
  [<C>shiftnet discover LEMMA</C>, 'Sample the word’s usages from fineweb-edu, cluster them with LexSPLADE and store the clusters as candidate senses.'],
  [<C>shiftnet candidates [--lemma W]</C>, 'Pending candidates with the nearest existing sense.'],
  [<C>shiftnet show ID</C>, 'A candidate’s terms, crawl years, and typical and borderline usages.'],
  [<C>shiftnet match ID [--sense S]</C>, 'Treat the candidate as an existing sense and quote its typical usages as attestations.'],
  [<C>shiftnet promote ID --pos … --gloss … --parent … --shift …</C>, 'Create a new sense from the candidate, with 2 examples and 3 attestations citing the web pages.'],
  [<C>shiftnet reject ID --note …</C>, 'Discard the candidate and record why.'],
  [<C>shiftnet relations suggest [WORDS…]</C>, 'Propose WordNet relations for the senses of these words (every sense when omitted).'],
  [<C>shiftnet relations show SENSE</C>, 'The stored suggestions for one sense.'],
];

const READ_TOOLS: Entry[] = [
  [<C>search_lexicon(query, limit)</C>, 'Head words and expressions matching a query.'],
  [<C>get_word(lemma)</C>, 'All senses of a word in registration order, with dates, shift types, parents and synonyms.'],
  [<C>get_sense(sense_id, attestations)</C>, 'One sense with its parents, children, relations and most relevant attestations.'],
  [<C>list_candidates(lemma, status, limit)</C>, 'Candidate senses from discovery runs: pending, matched, promoted, rejected or all.'],
  [<C>get_candidate(candidate_id, usages)</C>, 'A candidate’s terms, crawl-date spread, nearest existing sense and typical usages.'],
  [<C>get_relation_suggestions(sense_id)</C>, 'The relations LexSPLADE proposed for a sense, with scores.'],
];

const WRITE_TOOLS: Entry[] = [
  [<C>save_senses(senses)</C>, 'Insert or update senses, like shiftnet import.'],
  [<C>add_attestation(sense_id, attestation)</C>, 'Quote a dated usage for a sense, citing its source.'],
  [<C>discover_senses(lemma, forms, dumps, per_dump, threshold, min_size)</C>, 'Run sense discovery for a word. Slow: minutes on CPU.'],
  [<C>match_candidate(candidate_id, sense_id, attestations, note)</C>, 'Match a candidate to an existing sense.'],
  [<C>promote_candidate(candidate_id, promotion)</C>, 'Create a sense from a candidate, with part of speech, gloss and parents.'],
  [<C>reject_candidate(candidate_id, note)</C>, 'Discard a candidate.'],
  [<C>suggest_relations(lemmas, per_relation)</C>, 'Recompute relation suggestions. Slow: about 4 s per sense on CPU.'],
];

const TOC: [string, string][] = [
  ['website', 'The website'],
  ['contributing', 'Contributing'],
  ['backend', 'Backend tools'],
  ['mcp', 'MCP server'],
];

export function Docs() {
  useCrumbs([{ label: 'Documentation' }]);
  return (
    <article className="card prose">
      <section>
        <h1>Documentation</h1>
        <p>
          ShiftNet has three parts: this website, which reads the lexicon; Python tools that write to it and discover new
          senses in a web corpus; and an MCP server that lets an AI assistant do the same.
        </p>
        <nav aria-label="On this page">
          <ol className="doc-toc">
            {TOC.map(([id, label]) => (
              <li key={id}>
                <a href={`#${id}`}>{label}</a>
              </li>
            ))}
          </ol>
        </nav>
      </section>

      <section id="website" aria-labelledby="website-h">
        <h2 id="website-h">The website</h2>
        <p>
          Every sense carries the date it was first recorded and links to the senses it grew out of. Search a word, read its
          senses, then switch to the timeline to see which meaning came from which. Press <kbd>/</kbd> anywhere to jump to
          the search box.
        </p>
        <Terms items={PAGES} />
        <h3>Links that keep the view</h3>
        <p>
          Filters, order and the time-travel year live in the address, so a copied link opens exactly the same view. Every
          word and sense page has <em>Copy link</em> and <em>Cite</em> (APA and BibTeX).
        </p>
        <Terms items={PARAMS} />
      </section>

      <section id="contributing" aria-labelledby="contributing-h">
        <h2 id="contributing-h">Contributing</h2>
        <p>
          ShiftNet runs locally with one user, who both contributes and reviews. From the{' '}
          <Link to="/contribute">Contribute</Link> page, propose:
        </p>
        <Terms items={CONTRIB} />
        <p>
          Every proposal runs through automatic checks: required fields, the word appears in the quote, dates are
          consistent, the reference is well formed, no duplicates. <em>Run checks</em> shows the results before you
          submit. A failed check marked as an error refuses the proposal. One that only flags it sends it to the review
          queue. A proposal that passes everything is published at once as <em>Auto-checked</em>.
        </p>
        <p>
          In the <Link to="/review">review queue</Link>, accept or reject flagged proposals (a rejection keeps a note
          saying why), and confirm or withdraw auto-accepted ones.
        </p>
      </section>

      <section id="backend" aria-labelledby="backend-h">
        <h2 id="backend-h">Backend tools</h2>
        <p>
          The <C>backend/</C> package (Python 3.12, managed with uv) owns the database, a single SQLite file
          (<C>$SHIFTNET_DB</C>, by default <C>~/data/shiftnet.sqlite</C>). <C>shiftnet serve</C> is the API this website
          talks to; the other commands load and curate the lexicon.
        </p>
        <Code>{`
cd backend
uv sync --all-extras
uv run shiftnet serve                   # the API, http://127.0.0.1:8000
`}</Code>
        <Terms items={CLI} />
        <h3>Sense discovery</h3>
        <p>
          <C>discover</C> streams snapshots of the fineweb-edu web corpus (Common Crawl dumps from 2013 to 2025), takes the
          sentence around each occurrence of the word, and encodes it with LexSPLADE, which reads the marked word as a
          weighted list of vocabulary terms. Usages are clustered by similarity, and each cluster becomes a candidate sense
          with its strongest terms, crawl dates, usages per year and the closest existing sense. You then match, promote or
          reject each one.
        </p>
        <p>
          A crawl date only shows that a usage existed by then, so a promoted sense is dated by its first crawl year unless
          you give a date. For older senses, match rather than promote.
        </p>
        <h3>Relation suggestions</h3>
        <p>
          <C>relations suggest</C> uses the same encoder to propose synonyms, hypernyms and meronyms for each sense, and
          derives hyponyms and holonyms as their inverses. Each target is matched to the ShiftNet sense or taxonomy synset
          whose definition fits best. The scores are evidence for a person, not a decision: they appear next to the{' '}
          <em>Propose a relation</em> form. A proposed relation is published at once only when the model scores it 0.6 or
          more and the target word is in ShiftNet.
        </p>
      </section>

      <section id="mcp" aria-labelledby="mcp-h">
        <h2 id="mcp-h">MCP server</h2>
        <p>
          <C>shiftnet-mcp</C> exposes the lexicon and the discovery workflow to an assistant such as Claude Code or Claude
          Desktop. Read tools are always on. Tools that write are registered only with <C>SHIFTNET_MCP_WRITE=1</C>.
        </p>
        <Code>{`
uv run shiftnet-mcp                           # read-only, stdio
SHIFTNET_MCP_WRITE=1 uv run shiftnet-mcp      # with write tools
uv run shiftnet-mcp --transport streamable-http   # http://127.0.0.1:8000/mcp
`}</Code>
        <p>
          For Claude Code, copy <C>.mcp.json.example</C> at the repository root to <C>.mcp.json</C>:
        </p>
        <Code>{`
{
  "mcpServers": {
    "shiftnet": {
      "command": "uv",
      "args": ["run", "--project", "backend", "--extra", "mcp", "--extra", "discovery", "shiftnet-mcp"],
      "env": { "SHIFTNET_DB": "~/data/shiftnet.sqlite", "SHIFTNET_MCP_WRITE": "1" }
    }
  }
}
`}</Code>
        <h3>Read tools</h3>
        <Terms items={READ_TOOLS} />
        <h3>Write tools</h3>
        <Terms items={WRITE_TOOLS} />
        <p>
          A typical session: “run discovery for <em>stream</em>, then review the pending candidates”. The assistant reads
          each cluster’s usages, compares them with the word’s senses, matches or rejects it, and drafts a gloss and parent
          for a new sense.
        </p>
      </section>
    </article>
  );
}
