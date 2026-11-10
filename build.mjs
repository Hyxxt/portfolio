// 构建脚本：把静态站文件复制到 dist/，供帽子云等平台发布。
import { cp, mkdir, rm } from 'node:fs/promises';

const files = [
  'index.html',
  '作品集.html',
  'resume.pdf',
  'robots.txt',
  'sitemap.xml',
  '_headers',
  'img',
];

await rm('dist', { recursive: true, force: true });
await mkdir('dist', { recursive: true });

for (const file of files) {
  await cp(file, `dist/${file}`, { recursive: true });
}

console.log(`Built ${files.length} entries into dist/`);
