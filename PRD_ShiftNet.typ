// ShiftNet — Product Requirement Document
// Compile: typst compile PRD_ShiftNet.typ

#let navy = rgb("#2c3e50")
#let accent = rgb("#c0392b")
#let tip-fill = rgb("#fdf3d4")
#let tip-ink = rgb("#b9770e")
#let muted = rgb("#666666")
#let rule = rgb("#bdbdbd")

#set document(title: "PRD - ShiftNet")
#set page(
  paper: "a4",
  margin: (x: 2cm, top: 2.2cm, bottom: 2cm),
  header: align(right, text(8pt, style: "italic", fill: muted)[PRD - ShiftNet]),
  footer: context align(center, text(8pt)[
    Page #counter(page).display() / #counter(page).final().first()
  ]),
)
#set text(font: ("Liberation Sans", "DejaVu Sans"), size: 10pt, lang: "en")
#set par(leading: 0.55em, spacing: 0.9em)
#set list(indent: 1.5em)

#show heading.where(level: 1): it => block(above: 1.7em, below: 0.8em,
  text(15pt, weight: "bold", fill: accent, it.body))
#show heading.where(level: 2): it => block(above: 1.2em, below: 0.6em,
  text(10.5pt, weight: "bold", fill: navy, it.body))
#show figure.caption: set text(8.5pt, fill: muted)

// Yellow guidance note under each section title
#let tip(body) = block(width: 100%, fill: tip-fill, inset: (x: 6pt, y: 4pt),
  above: 0.6em, below: 1em,
  text(8.5pt, style: "italic", fill: tip-ink)[#text(style: "normal")[💡] #body])

#let story(id, title, body) = block(above: 1em, below: 0.4em, breakable: false)[
  #h(1.5em)#box(width: 4.2em)[#id.]#strong(title) \
  #body
]

#let criteria(title, ..items) = block(above: 1.1em, breakable: false)[
  #text(weight: "bold", fill: navy, title)
  #set list(marker: [☐], indent: 2.2em, body-indent: 0.6em, spacing: 0.45em)
  #list(..items.pos())
]

#let req-table(widths, head, ..cells) = table(
  columns: widths,
  stroke: 0.5pt + rule,
  inset: (x: 5pt, y: 3pt),
  fill: (_, y) => if y == 0 { navy },
  table.header(..head.map(h => table.cell(align: center,
    text(fill: white, weight: "bold", h)))),
  ..cells,
)

// Wireframe helpers
#let pill(label, on: false) = box(inset: (x: 6pt, y: 3pt), radius: 7pt,
  fill: if on { navy } else { none },
  stroke: 0.6pt + if on { navy } else { rule },
  text(7.5pt, fill: if on { white } else { muted }, label))
#let node(x, y, col, hollow: false) = place(dx: x - 3.5pt, dy: y - 3.5pt,
  circle(radius: 3.5pt, fill: if hollow { white } else { col }, stroke: 1.2pt + col))
#let branch(x1, y1, x2, y2, col) = place(curve(
  stroke: 1.5pt + col,
  curve.move((x1, y1)),
  curve.cubic((x1, y1 + 9pt), (x2, y1 + 7pt), (x2, y1 + 16pt)),
  curve.line((x2, y2)),
))
#let trunk(x, y1, y2, col) = place(line(start: (x, y1), end: (x, y2), stroke: 1.5pt + col))
#let cell-at(x, y, body) = place(dx: x, dy: y - 3.3pt, text(9pt, body))
#let tag-at(x, y, label) = place(dx: x, dy: y - 5.2pt, pill(label))
#let date-at(y, body) = place(top + right, dx: -12pt, dy: y - 3.3pt, text(9pt, body))


#text(24pt, weight: "bold")[Product Requirement Document]
#v(0.3em)
#text(12pt, fill: muted)[ShiftNet — A WordNet browser that shows how word meanings shift over time]


= 1. Vision & Goals
#tip[Explain the problem, your solution, and who you are building this product for.]

== Problem
WordNet browsers such as Open English WordNet (#link("https://en-word.net/")[en-word.net]) list a word's senses as a flat, timeless set. Nothing shows that the computing sense of _cloud_ grew out of the weather sense, or when that happened. Researchers who study semantic change rebuild these histories by hand from dictionaries and corpora.

== Solution
ShiftNet keeps the familiar en-word.net experience: search a word, then read its synsets, definitions, examples and relations. It adds time. Senses are listed by registration date, and a sense born from an earlier one branches off it, like commits in a git tree visualizer. Readers see at a glance how a word split, narrowed or drifted.

== Target users
- Historical linguists and lexicographers studying semantic change
- Computational linguists and NLP researchers who need dated, diachronic sense data
- Teachers and students exploring etymology and language change
- Curious readers who want the story behind a word


= 2. User Stories
#tip[Each user story = 1 feature. Format: "As a X, I want Y so that Z". One story = one screen or one action.]

#story("US1", "Home")[As a visitor, I want a home page with a search box and the latest registered senses so that I can start exploring right away.]
#story("US2", "Search")[As a user, I want suggestions while I type a word so that I reach its entry even with partial spelling.]
#story("US3", "Word entry")[As a user, I want to see all senses of a word grouped by part of speech, as on en-word.net, so that I know what the word means.]
#story("US4", "Sense lineage")[As a user, I want a word's senses listed by registration date, each linked to the sense it was born from like a git tree, so that I can see how its meaning shifted.]
#story("US5", "Global timeline")[As a user, I want to browse senses across the whole lexicon by registration date, in the same git-tree style, so that I can discover new meanings as they appear.]
#story("US6", "Sense detail")[As a user, I want to open a sense and see its definition, examples, date, parent sense, shift type and source so that I can check the evidence.]
#story("US7", "Relations")[As a user, I want to follow a sense's WordNet relations (synonyms, hypernyms, hyponyms and others) so that I can explore related words.]
#story("US8", "Time travel")[As a user, I want to pick a date so that I see a word's senses as they stood at that point in time.]
#story("US9", "Filters")[As a user, I want to filter senses by part of speech, shift type and date range so that I can focus on one pattern of change.]
#story("US10", "Share & cite")[As a user, I want a stable link and a ready-made citation for every word and sense so that I can reference them in my work.]


= 3. Acceptance Criteria
#tip[The conditions for a user story to count as "done". The AI uses them as a checklist.]

#criteria[US1 — Home][The search box is centred and focused when the page loads][The 10 most recently registered senses are listed below it, each with word, short gloss and date][A link opens the full global timeline]

#criteria[US2 — Search][Suggestions appear after 2 characters][Suggestions include multi-word expressions (e.g. "hot dog") and show the part of speech][Search ignores case and accents][A word with no match shows "No results" plus close spellings]

#criteria[US3 — Word entry][Senses are grouped by part of speech: noun, verb, adjective, adverb][Each sense shows its synonyms, definition and examples when available][Each sense shows its registration date][A toggle switches between the Senses view and the Timeline view (US4)]

#criteria[US4 — Sense lineage][One sense per row, sorted by registration date, oldest first (toggle: newest first)][A sense born from an earlier sense starts a new branch from its parent's node, as in #box[`git log --graph`]][A sense with two parents is drawn as a merge of both branches][Each branch has its own colour; a hollow node marks an obsolete sense and ends its branch][Hovering or focusing a node highlights its full ancestry back to the root sense][A parent sense that belongs to another word appears as a link to that word at the start of the branch]

#criteria[US5 — Global timeline][Rows list registered senses across the lexicon, newest first, with year separators][Same graph rules as US4; lines connect only senses of the same lineage][A branch whose parent is outside the loaded rows shows a short "from: parent sense, date" stub instead of a long line][Infinite scroll loads 50 rows at a time; a "Jump to year" control moves through time]

#criteria[US6 — Sense detail][Shows lemma, part of speech, definition, examples, registration date, date source and shift type][Parent and child senses are listed as links][A mini lineage graph shows the sense within its word's tree, with the current sense highlighted]

#criteria[US7 — Relations][Shows the synset's relations: synonyms, antonyms, hypernyms, hyponyms, meronyms, holonyms, derived forms][Each related word links to its entry][Relation groups with more than 10 items are collapsed by default]

#criteria[US8 — Time travel][A date slider spans the word's earliest to latest registration date][Senses registered after the chosen date are hidden; senses obsolete by then are greyed out][The chosen date is kept in the URL]

#criteria[US9 — Filters][Filters: part of speech, shift type (broadening, narrowing, metaphor, metonymy, amelioration, pejoration, other) and date range][Active filters show as removable chips][Filtered-out senses keep their lines as faint dashed connectors, so the lineage stays readable]

#criteria[US10 — Share & cite][Every word, sense and timeline state has a stable URL][A "Cite" button copies a citation in APA and BibTeX formats][Opening a shared URL restores the same view, filters and date]


= 4. Application Screens
#tip[List every screen. This helps the AI understand the app's structure and navigation.]

#req-table((32%, 68%), ("Screen", "Description"),
  [Home], [Search box + latest registered senses],
  [Search results], [Matching lemmas with part of speech and number of senses],
  [Word entry — Senses], [Senses grouped by part of speech, en-word.net style],
  [Word entry — Timeline], [Senses by registration date with the git-tree lineage graph],
  [Sense detail], [Definition, examples, date, source, parents, children, relations],
  [Global timeline], [All senses across the lexicon by date, git-tree style],
  [About & sources], [Project description, data sources, how dates are assigned, how to cite],
  [Not found], [Unknown word or sense, with spelling suggestions],
)

== Key screen: Word entry — Timeline

#figure(
  block(width: 100%, height: 214pt, stroke: 0.6pt + rule, radius: 4pt, clip: true)[
    // Title bar and view toggle
    #place(dx: 12pt, dy: 12pt, text(13pt)[*cloud* #h(4pt) #text(8.5pt, fill: muted)[noun · 4 senses]])
    #place(top + right, dx: -12pt, dy: 11pt, stack(dir: ltr, spacing: 4pt, pill("Senses"), pill("Timeline", on: true)))
    // Column headers
    #place(dx: 12pt, dy: 42pt, text(7.5pt, fill: muted)[LINEAGE])
    #place(dx: 104pt, dy: 42pt, text(7.5pt, fill: muted)[SENSE])
    #place(dx: 336pt, dy: 42pt, text(7.5pt, fill: muted)[SHIFT])
    #place(top + right, dx: -12pt, dy: 42pt, text(7.5pt, fill: muted)[REGISTERED])
    #place(dx: 12pt, dy: 56pt, line(length: 100% - 24pt, stroke: 0.6pt + rule))
    #for y in (96pt, 128pt, 160pt) {
      place(dx: 104pt, dy: y, line(length: 100% - 116pt, stroke: 0.4pt + rgb("#e6e6e6")))
    }
    // Lineage graph: lanes A (obsolete root), B, C, D
    #let (a, b, c, d) = (22pt, 38pt, 54pt, 70pt)
    #let (ca, cb, cc, cd) = (rgb("#9e9e9e"), rgb("#2e86c1"), rgb("#d35400"), rgb("#229954"))
    #branch(a, 83.5pt, b, 112pt, cb)
    #trunk(b, 112pt, 198pt, cb)
    #branch(b, 112pt, c, 144pt, cc)
    #trunk(c, 144pt, 198pt, cc)
    #branch(b, 112pt, d, 176pt, cd)
    #trunk(d, 176pt, 198pt, cd)
    #node(a, 80pt, ca, hollow: true)
    #node(b, 112pt, cb)
    #node(c, 144pt, cc)
    #node(d, 176pt, cd)
    #place(dx: 82pt, dy: 194pt, text(7.5pt, fill: muted)[still in use today])
    // Rows
    #cell-at(104pt, 80pt)[mass of rock; hill]
    #tag-at(336pt, 80pt, "root · obsolete")
    #date-at(80pt)[Old English]
    #cell-at(104pt, 112pt)[visible mass of water vapour in the sky]
    #tag-at(336pt, 112pt, "metaphor")
    #date-at(112pt)[c. 1300]
    #cell-at(104pt, 144pt)[a state of gloom or suspicion ("under a cloud")]
    #tag-at(336pt, 144pt, "metaphor")
    #date-at(144pt)[16th c.]
    #cell-at(104pt, 176pt)[remote servers reached over the internet]
    #tag-at(336pt, 176pt, "metaphor")
    #date-at(176pt)[1990s]
  ],
  caption: [Wireframe. Each colour is one branch of meaning, a curve is a sense born from an earlier one, and a hollow node is an obsolete sense. Sample data for "cloud"; dates are illustrative.],
)


= 5. Constraints
#tip[The non-negotiable rules the app must follow, on the interface and user-experience side.]

#req-table((24%, 76%), ("Constraint", "Requirement"),
  [Desktop-first], [Designed first for desktop browsers (research use), then adapted to tablet and phone],
  [Performance], [A word entry with up to 100 senses loads in under 2 seconds],
  [Familiarity], [Layout and terms follow en-word.net: synset, lemma, gloss, relation names],
  [Graph readability], [At most 8 branches side by side; extra branches fold into a "+n branches" marker],
  [Accessibility], [WCAG 2.1 AA; branches never differ by colour alone; every row states its parent sense in text; full keyboard navigation],
  [Fuzzy dates], [Dates may be exact, a year, a decade or a century ("c. 1300", "16th c."); rows sort by the earliest possible date and show the date as recorded],
  [Provenance], [Every date and parent link shows its source (dictionary, corpus, citation)],
  [Open access], [Browsing needs no account],
  [Responsive], [On phones the graph shrinks to a narrow strip and rows stay readable],
  [Feedback], [The user always sees what is happening (loading, empty result, error)],
  [Language], [Interface and lexicon in English],
)


= 6. Out of Scope (MVP)
- No editing or submitting senses from the interface; the ShiftNet team loads the data
- No user accounts, favourites or saved searches
- No languages other than English
- No side-by-side comparison of two words' timelines (planned for v2)
- No per-sense frequency charts from corpora
- No automatic detection of new senses in the interface
- No public API or bulk download from the interface

#v(0.8em)
#tip[*Tip:* This PRD covers the WHAT (screens, features). The technical HOW (ShiftNet data format, database, APIs) comes next, once the interface is validated.]
