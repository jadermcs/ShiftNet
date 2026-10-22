# ShiftNet design system

ShiftNet is a WordNet browser that adds time: each sense has a registration date and a parent sense, drawn as a git-style lineage graph.

Sources: `uploads/PRD_ShiftNet.pdf`; layout reference https://lrec.elra.info/conference/2026/main (dark sidebar shell, bordered cards, mono index numbers); graph reference: a git client's commit graph (screenshot) — coloured lanes, curved branches, branch-tinted rows.

## Files
- `ShiftNet.dc.html` — interactive prototype of every PRD screen (Home, Search results, Word entry Senses/Timeline, Sense detail, Global timeline, About & sources, Not found). State lives in the URL hash.
- `ShiftNet Design System.dc.html` — foundations and component specimens.
- `styles.css` → `tokens/colors.css`, `tokens/typography.css`, `tokens/spacing.css`.

## Content
- Plain, factual, sentence case. Terms follow en-word.net: synset, lemma, gloss, sense, hypernym.
- Dates are shown exactly as recorded (`c. 1300`, `16th c.`, `1990s`) in mono.
- Sense tags: `n. 2`, `v. 1`, `adj. 3`. Shift types lowercase: broadening, narrowing, metaphor, metonymy, amelioration, pejoration, other (+ `root`).
- Every row states its parent in text ("from n. 1", "root sense"). No emoji.

## Visual foundations
- Dark neutral UI (#0a0a0a page, #111 cards, #262626 borders). One light element per view: the white primary button.
- Colour is reserved for lineage. Eight branch colours, assigned in registration order within a word; never used for chrome. Shift types are neutral outlined chips.
- Branches never differ by colour alone: each has a letter (A–H) printed in the row, and the parent is written out.
- Graph: nodes 5.5px; filled = in use, hollow = obsolete (branch ends), outer ring = merge of two parents, white ring = current sense, dashed = filtered out, short dotted stub = parent outside the loaded rows. A new branch curves out of its parent's node; a merge curves into the child.
- Rows carry a faint branch-colour band starting at the node (10% → 0), stronger on hover/focus. Hover/focus highlights the full ancestry; everything else drops to 16%.
- Type: IBM Plex Sans for UI and glosses, IBM Plex Mono for indices, dates, tags and column labels (uppercase, +0.08em).
- Radii 6 / 8 / 10 / pill. No shadows except dropdowns. No gradients other than the row tint. Transitions minimal.

## Iconography
Lucide via `lucide-static` icon font (CDN), 14–18px, stroke style matches the reference site. No custom icons; no brand logo exists — the wordmark is "ShiftNet" set in Plex Sans Bold.
