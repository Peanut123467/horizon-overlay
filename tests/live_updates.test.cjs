// Exercise the actual panel script with a deterministic clock and slow API calls.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function harness(latency = 5) {
  let now = 0, serial = 0;
  const timers = new Map(), frames = [], patches = [], previews = [], errors = [], intervals = [];
  const active = { patch: 0, preview: 0 }, peak = { patch: 0, preview: 0 };
  function later(fn, ms) {
    const id = ++serial;
    timers.set(id, { at: now + ms, fn });
    return id;
  }
  const settle = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
  async function tick(ms) {
    await settle();
    const until = now + ms;
    let steps = 0;
    while (true) {
      if (++steps > 1000) throw new Error(`timer loop at ${now}: ${JSON.stringify([...timers.values()].map(t => t.at))}`);
      const next = [...timers.entries()].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      now = next[1].at;
      timers.delete(next[0]);
      next[1].fn();
      await settle();
    }
    now = until;
    await settle();
  }
  const delay = () => new Promise(resolve => later(resolve, latency));
  const copy = value => JSON.parse(JSON.stringify(value));
  let saved = { frame: { width: 1, alpha: 100 } };
  const api = {
    monitors: async () => [],
    hotkey_options: async () => ({}),
    startup: async () => false,
    state: async () => ({ config: copy(saved), overlay_alive: false }),
    async patch(body) {
      const snapshot = copy(body);
      patches.push(snapshot);
      for (const [group, values] of Object.entries(snapshot)) {
        saved[group] = { ...saved[group], ...values };
      }
      const config = copy(saved);
      peak.patch = Math.max(peak.patch, ++active.patch);
      await delay();
      --active.patch;
      return { config, overlay_alive: false };
    },
    async preview(cfg) {
      const snapshot = copy(cfg);
      previews.push(snapshot);
      peak.preview = Math.max(peak.preview, ++active.preview);
      await delay();
      --active.preview;
      return `frame-${snapshot.frame.width}`;
    },
  };
  const image = { addEventListener() {}, set src(value) { frames.push(value); }, get src() { return frames.at(-1); } };
  const context = vm.createContext({
    setTimeout: later, clearTimeout: id => timers.delete(id), __api: api, __errors: errors,
    setInterval: fn => { intervals.push(fn); return intervals.length; },
    window: { addEventListener() {}, pywebview: { api } },
    document: { addEventListener() {}, querySelector: selector => selector === '[data-recording="true"]' ? null : image, querySelectorAll: () => [], hasFocus: () => false, activeElement: { tagName: 'BODY' } },
  });
  vm.runInContext(readFileSync(join(__dirname, '../src/horizon/console/ui/app.js'), 'utf8'), context);
  vm.runInContext('api=__api; cfg={frame:{width:1,alpha:100}}; setStatus=()=>{}; showError=e=>__errors.push(String(e)); renderState=state=>{cfg=state.config;queuePreview();};', context);
  const run = text => vm.runInContext(text, context, { timeout: 1000 });
  return { run, tick, frames, patches, previews, errors, peak, api, delay, intervals };
}

test('preview changes repeatedly before continuous dragging stops', async () => {
  const h = harness();
  for (let value = 2; value <= 21; value++) {
    h.run(`cfg.frame.width=${value}; queuePreview();`);
    await h.tick(20);
  }
  assert.ok(h.frames.length >= 3, 'preview stayed frozen while input kept arriving');
  await h.tick(250);
  assert.equal(h.frames.at(-1), 'frame-21');
});

test('patches reach the backend repeatedly during continuous dragging', async () => {
  const h = harness();
  for (let value = 2; value <= 21; value++) {
    h.run(`queuePatch({frame:{width:${value}}});`);
    await h.tick(20);
  }
  assert.ok(h.patches.length >= 3, 'backend updates were postponed until input stopped');
  const flushed = h.run('flushPatch()');
  await h.tick(250);
  await flushed;
  assert.equal(h.patches.at(-1).frame.width, 21);
});

test('slow previews still display progress and eventually show the latest value', async () => {
  const h = harness(120);
  for (let value = 2; value <= 61; value++) {
    h.run(`cfg.frame.width=${value}; queuePreview();`);
    await h.tick(10);
  }
  assert.ok(h.frames.length >= 2, 'slow preview results were all discarded during dragging');
  await h.tick(500);
  assert.equal(h.frames.at(-1), 'frame-61');
  assert.equal(h.peak.preview, 1);
  assert.ok(h.previews.length <= 8, 'obsolete preview requests accumulated');
});

test('slow patch API coalesces pending edits and keeps at most one request in flight', async () => {
  const h = harness(120);
  for (let value = 2; value <= 61; value++) {
    h.run(`queuePatch({frame:{width:${value}}});`);
    await h.tick(10);
  }
  assert.ok(h.patches.length >= 2, 'no live backend progress');
  const flushed = h.run('flushPatch()');
  await h.tick(500);
  await flushed;
  assert.equal(h.patches.at(-1).frame.width, 61);
  assert.equal(h.peak.patch, 1);
  assert.ok(h.patches.length <= 8, 'obsolete patch requests accumulated');
});

test('explicit flush waits for the final merged values even with an active request', async () => {
  const h = harness(80);
  h.run('queuePatch({frame:{width:21,alpha:100}})');
  const first = h.run('flushPatch()');
  await h.tick(20);
  h.run('queuePatch({frame:{width:50}}); queuePatch({frame:{alpha:140}});');
  const second = h.run('flushPatch()');
  await h.tick(500);
  await Promise.all([first, second]);
  assert.deepEqual(h.patches.at(-1), { frame: { width: 50, alpha: 140 } });
  assert.equal(h.errors.length, 0);
});

test('an already running background poll cannot restore stale slider values', async () => {
  const h = harness(40);
  h.run('renderState = state => { cfg=state.config; queuePreview(); }; bindAction=()=>{}; bootStudio=async()=>{};');
  await h.run('boot()');
  assert.equal(h.intervals.length, 1);
  await h.tick(100);
  h.api.state = async () => {
    await h.delay();
    return { config: { frame: { width: 1, alpha: 100 } }, overlay_alive: false };
  };
  const polling = h.intervals[0]();
  await h.tick(10);
  h.run('cfg.frame.width=99; queuePatch({frame:{width:99}}); queuePreview();');
  await h.tick(300);
  await polling;
  assert.equal(h.run('cfg.frame.width'), 99, 'stale polling response replaced the current slider value');
  assert.equal(h.patches.at(-1).frame.width, 99);
  assert.equal(h.frames.at(-1), 'frame-99');
});

test('patch acknowledgement cannot overwrite a newer slider edit', async () => {
  const h = harness(80);
  h.run("setValue('frame','width',21)");
  await h.tick(60);
  h.run("setValue('frame','width',31)");
  await h.tick(80);
  assert.equal(h.run('cfg.frame.width'), 31);
  await h.tick(200);
  assert.equal(h.run('cfg.frame.width'), 31);
  assert.equal(h.errors.length, 0);
});

test('backend canonical values are used after the final edit completes', async () => {
  const h = harness(40);
  h.api.patch = async () => {
    await h.delay();
    return { config: { frame: { width: 10, alpha: 100 } }, overlay_alive: false };
  };
  h.run("setValue('frame','width',99)");
  await h.tick(200);
  assert.equal(h.run('cfg.frame.width'), 10);
  assert.equal(h.frames.at(-1), 'frame-10');
});

test('in-flight preview from the previous background is discarded', async () => {
  const h = harness(120);
  h.run('queuePreview()');
  await h.tick(40);
  h.run('previewGeneration++; previewSourceChanging=true;');
  await h.tick(150);
  assert.equal(h.frames.length, 0, 'old background was painted after switching sources');
  h.run('cfg.frame.width=9; previewSourceChanging=false; queuePreview();');
  await h.tick(250);
  assert.equal(h.frames.at(-1), 'frame-9');
});

test('source import pauses previews and resumes with the latest edit', async () => {
  const h = harness(20);
  h.run('previewSourceChanging=true; queuePreview();');
  await h.tick(500);
  assert.equal(h.previews.length, 0);
  h.run('cfg.frame.width=71; previewSourceChanging=false; queuePreview();');
  await h.tick(100);
  assert.equal(h.frames.at(-1), 'frame-71');
});
