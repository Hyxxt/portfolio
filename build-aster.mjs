// Build only the standalone Aster Precision copy for its own Maozi app.
// The main portfolio build remains build.mjs / dist and is unaffected.
import { mkdir, readdir, readFile, writeFile, rm, stat } from 'node:fs/promises';
import { join } from 'node:path';

const source = 'aster-site';
const target = 'aster-dist';

async function copy(src, dest) {
  const info = await stat(src);
  if (info.isDirectory()) {
    await mkdir(dest, { recursive: true });
    for (const name of await readdir(src)) {
      await copy(join(src, name), join(dest, name));
    }
  } else {
    await writeFile(dest, await readFile(src));
  }
}

await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });

for (const name of await readdir(source)) {
  await copy(join(source, name), join(target, name));
}

console.log(`Built Aster Precision into ${target}/`);
