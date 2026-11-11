import { appendFileSync, readFileSync } from 'node:fs';

// Angular extracts code licenses; include the notice for our self-hosted font too.
const license = readFileSync(
  new URL('../node_modules/@fontsource-variable/mona-sans/LICENSE', import.meta.url),
  'utf8',
);
appendFileSync(
  new URL('../dist/3rdpartylicenses.txt', import.meta.url),
  `\n\nMona Sans\n${license}\n`,
);
