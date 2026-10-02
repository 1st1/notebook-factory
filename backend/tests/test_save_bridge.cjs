const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function bridge(context) {
  const handlers = {};
  const parent = {};
  const shell = { currentWidget: { context }, currentChanged: { connect() {} } };
  const window = {
    location: { href: 'https://sandbox.test/token/doc/tree/notebook.ipynb', pathname: '/token/doc/tree/notebook.ipynb' },
    jupyterapp: { shell, restored: new Promise(() => {}) },
    parent,
    addEventListener: (name, callback) => { handlers[name] = callback; },
    setTimeout() {},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../assets/jupyter_bridge.js'), 'utf8'), {
    window, URL, WeakSet, Promise,
    document: { documentElement: {} },
    ResizeObserver: class { observe() {} },
    __PARENT_ORIGIN__: 'https://app.test',
  });
  return { handlers, parent };
}

// @lat: [[editing#Save serialization]]
test('native and bridge saves wait for the preceding metadata refresh', async () => {
  let release, started = 0;
  const context = {
    path: 'notebook.ipynb', ready: Promise.resolve(),
    async save() {
      started++;
      if (started === 1) await new Promise(resolve => { release = resolve; });
    },
  };
  const { handlers, parent } = bridge(context);
  const first = context.save();
  await Promise.resolve();
  let acknowledged = false;
  parent.postMessage = () => { acknowledged = true; };
  const second = handlers.message({ source: parent, origin: 'https://app.test', data: {
    type: 'vercel-notebook-save', token: 'token', id: 'save-2',
  } });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(started, 1);
  assert.equal(acknowledged, false);
  release();
  await Promise.all([first, second]);
  assert.equal(started, 2);
  assert.equal(acknowledged, true);
});

test('a failed save stays rejected without blocking later saves', async () => {
  let attempts = 0;
  const context = { async save() { if (++attempts === 1) throw Error('Save cancelled'); } };
  bridge(context);
  const first = context.save();
  const second = context.save();
  await assert.rejects(first, /Save cancelled/);
  await second;
  assert.equal(attempts, 2);
});
