#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const srcDir = path.join(root, 'daemon');
const distDir = path.join(root, 'dist');
const destDir = path.join(distDir, 'daemon');

if (!fs.existsSync(srcDir)) {
  console.error(`Source daemon directory not found at ${srcDir}`);
  process.exit(1);
}

// Ensure dist directory exists
fs.mkdirSync(distDir, { recursive: true });

// Clean previous packaged daemon directory if it exists
fs.rmSync(destDir, { recursive: true, force: true });
fs.mkdirSync(destDir, { recursive: true });

function shouldExclude(sourcePath) {
  const relPath = path.relative(srcDir, sourcePath);
  if (!relPath) {
    return false;
  }
  const segments = relPath.split(path.sep);

  if (segments.includes('tests') || segments.includes('__pycache__') || segments.includes('.pytest_cache')) {
    return true;
  }
  if (sourcePath.endsWith('.pyc')) {
    return true;
  }
  return false;
}

fs.cpSync(srcDir, destDir, {
  recursive: true,
  filter: (source) => !shouldExclude(source),
});

console.log(`Successfully packaged daemon to ${destDir}`);
