import { useCrumbs } from '../components/Shell';

const SHIFTS: [string, string][] = [
  ['broadening', 'the sense covers more than before'],
  ['narrowing', 'the sense covers less than before'],
  ['metaphor', 'transfer based on likeness'],
  ['metonymy', 'transfer based on association'],
  ['amelioration', 'the sense becomes more positive'],
  ['pejoration', 'the sense becomes more negative'],
  ['other', 'any other change, such as conversion to a new part of speech'],
];

export function About() {
  useCrumbs([{ label: 'About & sources' }]);
  const year = new Date().getFullYear();
  return (
    <article className="card prose">
      <section>
        <h1>About &amp; sources</h1>
        <p>
          ShiftNet adds dates to Open English WordNet. Each sense carries the date it was first recorded and a link to the
          sense it grew out of, so a word’s entry reads as a history as well as a list of meanings.
        </p>
      </section>
      <section>
        <h2>Data sources</h2>
        <p>
          Synsets, glosses and relations come from Open English WordNet. Dates and parent links come from historical
          dictionaries, dated corpora and individual citations. Every date and parent link names its source on the sense
          page. Dates in the sample lexicon are illustrative.
        </p>
      </section>
      <section>
        <h2>How dates are assigned</h2>
        <p>
          A sense is dated by its earliest recorded use. Dates are shown as recorded: an exact date, a year, a decade or a
          century, such as <span className="mono">c. 1300</span> or <span className="mono">16th c.</span> Rows sort by the
          earliest possible date.
        </p>
      </section>
      <section>
        <h2>Shift types</h2>
        <dl className="shift-list">
          {SHIFTS.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section>
        <h2>How to cite</h2>
        <p>Use the Cite button on any word or sense for APA and BibTeX. For the resource as a whole:</p>
        <div className="cite-text">
          ShiftNet. ({year}). ShiftNet: A WordNet browser for meaning over time. {window.location.origin}
        </div>
      </section>
    </article>
  );
}
