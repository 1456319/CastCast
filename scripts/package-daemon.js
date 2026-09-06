// synchronization-map: section=operations-release; role=package-daemon; boundaries=android-bridge,core-service; doc=docs/SYNCHRONIZATION_MAP.md
import { cp, mkdir, readFile, readdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = path.join(root, 'daemon');
const destination = path.join(root, 'dist', 'daemon');

// Regenerate only this build-owned directory. Never ship Python bytecode,
// previous daemon modules, test fixtures or test credentials in the APK.
await rm(destination, { recursive: true, force: true });
await mkdir(destination, { recursive: true });
await cp(source, destination, {
  recursive: true,
  filter: (file) => !path.relative(source, file).split(path.sep).some(
    (part) => part === 'tests' || part === '__pycache__' || part.startsWith('.') || part.endsWith('.pyc'),
  ),
});

async function verify(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const packaged = path.join(directory, entry.name);
    if (entry.isDirectory()) await verify(packaged);
    else {
      const original = path.join(source, path.relative(destination, packaged));
      if (!(await readFile(original)).equals(await readFile(packaged))) {
        throw new Error(`Daemon bundle differs from source: ${original}`);
      }
    }
  }
}
await verify(destination);
