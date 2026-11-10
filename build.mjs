// 构建脚本：把静态站文件复制到 dist/，供帽子云等平台发布。
import { mkdir, readdir, readFile, writeFile, rm, stat } from 'node:fs/promises';
import { join } from 'node:path';

const files = [
  'index.html',
  '作品集.html',
  'resume.pdf',
  'robots.txt',
  'sitemap.xml',
  '_headers',
  'img',
];

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

await rm('dist', { recursive: true, force: true });
await mkdir('dist', { recursive: true });

for (const file of files) {
  await copy(file, `dist/${file}`);
}

console.log(`Built ${files.length} entries into dist/`);
