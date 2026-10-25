import { build } from 'vite';
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('.', import.meta.url));
const outDir = path.resolve(root, '../../design-dist/weather');
await build({ configFile: false, root, base: './', build: { outDir, emptyOutDir: true } });
let html = await readFile(path.join(outDir, 'index.html'), 'utf8');
for (const match of [...html.matchAll(/<script\b[^>]*src="([^"]+)"[^>]*><\/script>/g)]) {
  const source = await readFile(path.join(outDir, match[1]), 'utf8');
  html = html.replace(match[0], () => `<script type="module">${source.replace(/<\/script/gi, '<\\/script')}</script>`);
}
for (const match of [...html.matchAll(/<link\b[^>]*href="([^"]+\.css)"[^>]*>/g)]) {
  const css = await readFile(path.join(outDir, match[1]), 'utf8');
  html = html.replace(match[0], () => `<style>${css}</style>`);
}
await writeFile(path.join(outDir, 'preview.html'), html);
console.log('Standalone animated preview: field_web/design-dist/weather/preview.html');
