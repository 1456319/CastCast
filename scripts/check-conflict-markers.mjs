#!/usr/bin/env node
import { execFileSync } from 'node:child_process';

const excludedGlobs = [
  '!node_modules',
  '!dist',
  '!pnpm-lock.yaml',
  '!handoff/REASONING_AND_RESEARCH.append.txt',
  '!scripts/check-conflict-markers.mjs',
];

try {
  execFileSync(
    'rg',
    [
      '--line-number',
      ...excludedGlobs.flatMap((glob) => ['-g', glob]),
      '-e',
      '^(<{7}|={7}|>{7})(?: |$)',
      '.',
    ],
    { stdio: 'pipe' },
  );
  console.error('Found merge conflict markers. Resolve them before committing.');
  process.exit(1);
} catch (error) {
  if (error.status === 1) {
    console.log('No merge conflict markers found.');
    process.exit(0);
  }
  throw error;
}
