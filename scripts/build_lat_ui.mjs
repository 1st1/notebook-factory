import { spawnSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const temporary = process.env.LAT_SOURCE_DIR ? null : await mkdtemp(join(tmpdir(), 'notebook-lat-'));
const toolchain = process.env.LAT_SOURCE_DIR ? resolve(process.env.LAT_SOURCE_DIR) : join(temporary, 'source');
const output = join(root, '.lat-build', 'static');
const destination = join(root, 'frontend', 'public', 'lat');

function run(command, args, cwd = toolchain) {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit', env: process.env });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} failed (${result.status})`);
}
const pnpm = (...args) => run('npx', ['--yes', 'pnpm@10.30.2', ...args]);

// @lat: [[deployment#Static project documentation]]
try {
  if (temporary) run('git', ['clone', '--depth', '1', '--branch', 'main', '--single-branch', 'https://github.com/vercel-labs/lat.md.git', toolchain], root);
  run('git', ['rev-parse', 'HEAD']);
  pnpm('install', '--frozen-lockfile');
  pnpm('--filter', '@lat.md/server', 'build');
  // Lat's own build helper installs published embedding binaries without Rust.
  pnpm('exec', 'env', '-u', 'npm_execpath', 'node', 'scripts/prepare-site-packages.mjs');
  pnpm('build');
  run('node', [join(toolchain, 'dist/src/cli/index.js'), '--dir', root, 'ui', 'build', 'static', output, '--base', '/lat/', '--logo-text', 'Python Notebooks', '--force'], root);
  await mkdir(dirname(destination), { recursive: true });
  await rm(destination, { recursive: true, force: true });
  // The exporter also emits a root redirect; copy only /lat to preserve the app.
  await cp(join(output, 'lat'), destination, { recursive: true });
} finally {
  if (temporary) await rm(temporary, { recursive: true, force: true });
}
