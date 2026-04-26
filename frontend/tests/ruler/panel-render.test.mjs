import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

// Tiny DOM-element factory for tests — produces just enough to satisfy ruler.js.
function makeEl(tagName, parent) {
  var children = [];
  var attrs = {};
  var classList = new Set();
  var listeners = {};
  var el = {
    tagName: tagName.toUpperCase(),
    children: children,
    childNodes: children,
    get firstChild() { return children[0] || null; },
    appendChild: function (c) { children.push(c); c._parent = el; return c; },
    removeChild: function (c) {
      var idx = children.indexOf(c);
      if (idx >= 0) children.splice(idx, 1);
      return c;
    },
    setAttribute: function (k, v) { attrs[k] = v; },
    getAttribute: function (k) { return attrs[k]; },
    classList: {
      add: function (c) { classList.add(c); },
      remove: function (c) { classList.delete(c); },
      contains: function (c) { return classList.has(c); },
      toggle: function (c, on) { if (on) classList.add(c); else classList.delete(c); },
    },
    addEventListener: function (k, fn) { (listeners[k] = listeners[k] || []).push(fn); },
    removeEventListener: function () {},
    style: {},
    hidden: false,
    textContent: '',
    _attrs: attrs,
    _classList: classList,
    _listeners: listeners,
  };
  if (parent) parent.appendChild(el);
  return el;
}

function makeMeasurePanelDocument() {
  var elems = {};
  function id(name, tag) {
    elems[name] = makeEl(tag || 'div');
    elems[name].id = name;
    return elems[name];
  }
  id('measure-panel'); id('ruler-idle-hint', 'p');
  id('ruler-banner-inline'); id('ruler-banner-inline-text', 'span');
  id('ruler-banner-inline-cancel', 'button');
  id('ruler-headline-section'); id('ruler-headline-total');
  id('ruler-vertex-section'); id('ruler-vertex-count', 'span');
  id('ruler-vertex-list', 'ol');
  id('ruler-action-row'); id('ruler-action-empty', 'p');
  id('ruler-insert-before', 'button'); id('ruler-insert-after', 'button');
  id('ruler-delete-vertex', 'button');
  id('ruler-elevation-section'); id('ruler-sparkline', 'svg');
  id('ruler-stats'); id('ruler-stat-min'); id('ruler-stat-max');
  id('ruler-stat-gain'); id('ruler-stat-loss');
  id('ruler-coverage-warn');
  id('ruler-footer'); id('ruler-undo', 'button'); id('ruler-clear', 'button');
  id('ruler-finish', 'button'); id('ruler-new', 'button');
  id('ruler-mode-banner'); id('ruler-mode-banner-text', 'span');
  id('ruler-mode-banner-cancel', 'button');
  id('ruler-sampling-progress'); id('ruler-sampling-counter');
  return {
    getElementById: function (n) { return elems[n] || null; },
    addEventListener: function () {},
    createElement: function (tag) { return makeEl(tag); },
    elems: elems,
  };
}

test('renderPanel idle state: empty placeholder, finish hidden', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-headline-section'].hidden, true);
  assert.strictEqual(doc.elems['ruler-vertex-section'].hidden, true);
  assert.strictEqual(doc.elems['ruler-finish'].hidden, true);
  assert.strictEqual(doc.elems['ruler-clear'].hidden, true);
  assert.strictEqual(doc.elems['ruler-mode-banner'].hidden, true);
});

test('renderPanel drawing state: banner visible, vertex list rendered', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-mode-banner'].hidden, false);
  assert.strictEqual(doc.elems['ruler-vertex-section'].hidden, false);
  assert.strictEqual(doc.elems['ruler-vertex-list'].children.length, 2);
});

test('renderPanel uses textContent (NEVER innerHTML)', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.renderPanel();
  // Walk all rendered elements; none should have innerHTML set.
  function walk(el) {
    assert.strictEqual('innerHTML' in el ? el.innerHTML : undefined, undefined,
      'innerHTML must never be assigned');
    (el.children || []).forEach(walk);
  }
  walk(doc.elems['ruler-vertex-list']);
});

test('renderPanel editing state: action row + new measurement button visible', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.renderPanel();
  // Action row visibility depends on selectedVertex; nothing selected yet
  // so action-empty should show, action-row hidden.
  assert.strictEqual(doc.elems['ruler-action-empty'].hidden, false);
  assert.strictEqual(doc.elems['ruler-action-row'].hidden, true);
  assert.strictEqual(doc.elems['ruler-clear'].hidden, false);
  assert.strictEqual(doc.elems['ruler-new'].hidden, false);
});

test('renderPanel editing with selection: action row visible, empty hidden', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-action-row'].hidden, false);
  assert.strictEqual(doc.elems['ruler-action-empty'].hidden, true);
});

test('renderPanel: vertex count badge tracks state', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.03, 33.47);
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-vertex-count'].textContent, '3');
});

test('renderPanel idle: [+ New measurement] button is visible (explicit-activation entry point)', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-new'].hidden, false, 'idle should show [+ New measurement] button');
  assert.strictEqual(doc.elems['ruler-finish'].hidden, true);
  assert.strictEqual(doc.elems['ruler-clear'].hidden, true);
  assert.strictEqual(doc.elems['ruler-undo'].hidden, true);
  assert.strictEqual(doc.elems['ruler-idle-hint'].hidden, false);
});
