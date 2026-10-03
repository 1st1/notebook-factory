import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// @lat: [[deployment#Static project documentation]]
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'frontend', 'dist');
const html = await readFile(join(root, 'lat', 'index.html'), 'utf8');
assert.match(html, /lat-static-bootstrap/);
assert.match(html, /\/lat\/assets\//);
assert.doesNotMatch(await readFile(join(root, 'index.html'), 'utf8'), /lat-redirect/);
const manifest = JSON.parse(await readFile(join(root, 'lat', 'data', 'manifest.json'), 'utf8'));
assert.ok(Object.keys(manifest.documents).length >= 6, 'Export project documents');
assert.ok(Object.keys(manifest.sources).length > 0, 'Export linked source views');
for (const route of ['architecture', 'deployment', 'graph', 'code/backend/main.py']) {
  assert.ok((await stat(join(root, 'lat', route, 'index.html'))).isFile(), `Missing deep link: ${route}`);
}
console.log('PASS: /lat entry, assets, document/graph/source deep links, and separate app shell');
