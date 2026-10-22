const RESOURCE = 'ShiftNet: A WordNet browser for meaning over time';

export function citations(title: string, key: string, url: string, now = new Date()) {
  const year = now.getFullYear();
  const accessed = now.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  const apa = `ShiftNet. (${year}). ${title}. In ${RESOURCE}. Retrieved ${accessed}, from ${url}`;
  const bibtex = [
    `@misc{shiftnet_${key.replace(/\W/g, '_')},`,
    `  title = {${title}},`,
    `  author = {{ShiftNet}},`,
    `  year = {${year}},`,
    `  howpublished = {\\url{${url}}},`,
    `  note = {Accessed ${accessed}}`,
    `}`,
  ].join('\n');
  return { apa, bibtex };
}
