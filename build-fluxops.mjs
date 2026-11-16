import { cp, mkdir, readdir, rm } from 'node:fs/promises';
import { join } from 'node:path';

const source = 'fluxops-static';
const target = 'fluxops-dist';

await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });

for (const name of await readdir(source)) {
  if (name === 'README.md') continue;
  await cp(join(source, name), join(target, name), { recursive: true });
}

console.log(`Built FluxOps static site into ${target}/`);
