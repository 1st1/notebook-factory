const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function bridge(context, content) {
  const handlers = {};
  const parent = {};
  const shell = { currentWidget: { context, content }, currentChanged: { connect() {} } };
  const window = {
    location: { href: 'https://sandbox.test/token/doc/tree/notebook.ipynb', pathname: '/token/doc/tree/notebook.ipynb' },
    jupyterapp: { shell, restored: new Promise(() => {}) },
    parent,
    addEventListener: (name, callback) => { const previous = handlers[name]; handlers[name] = previous ? async event => { await previous(event); await callback(event); } : callback; },
    setTimeout() {},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../assets/jupyter_bridge.js'), 'utf8'), {
    window, URL, WeakSet, Promise,
    document: { documentElement: {} },
    ResizeObserver: class { observe() {} },
    __PARENT_ORIGIN__: 'https://app.test',
  });
  return { handlers, parent, shell };
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

// @lat: [[chat#Live document tests]]
test('chat reads unsaved cells and refuses stale replacements or untrusted messages', async () => {
  let source = 'print(42)';
  const cell = { getId: () => 'cell-1', getSource: () => source,
    setSource: value => { source = value; }, toJSON: () => ({ cell_type: 'code', source, outputs: [] }) };
  const { handlers, parent } = bridge({ path: 'notebook.ipynb', ready: Promise.resolve(), save() {} },
    { model: { sharedModel: { cells: [cell] } } });
  let response;
  parent.postMessage = value => { response = value; };
  async function call(tool, args, overrides = {}) {
    response = undefined;
    handlers.message({ source: parent, origin: 'https://app.test', data: {
      type: 'vercel-notebook-tool', token: 'token', id: 'tool-1', tool, args,
    }, ...overrides });
    await new Promise(resolve => setImmediate(resolve));
    return response;
  }
  assert.equal((await call('read_notebook', {})).result.cells[0].source, source);
  assert.match((await call('replace_cell', { cell_id: 'cell-1', expected_source: 'old', source: 'bad' })).error, /changed/);
  assert.equal(source, 'print(42)');
  assert.equal(await call('replace_cell', {}, { origin: 'https://evil.test' }), undefined);
  assert.equal(await call('read_notebook', {}, { source: {} }), undefined);
  await call('replace_cell', { cell_id: 'cell-1', expected_source: source, source: 'print(43)' });
  assert.equal(source, 'print(43)');
});

// @lat: [[chat#Unfocused notebook saves]]
test('save finds the open notebook when Jupyter has no focused widget', async () => {
  let saved = 0;
  const context = { path: 'notebook.ipynb', ready: Promise.resolve(), async save() { saved++; } };
  const { handlers, parent, shell } = bridge(context);
  const widget = shell.currentWidget;
  shell.currentWidget = null;
  shell.widgets = function* () { yield widget; };
  let response;
  parent.postMessage = value => { response = value; };
  await handlers.message({ source: parent, origin: 'https://app.test', data: {
    type: 'vercel-notebook-save', token: 'token', id: 'save-unfocused',
  } });
  assert.equal(saved, 1);
  assert.equal(response.type, 'vercel-notebook-saved');
});
