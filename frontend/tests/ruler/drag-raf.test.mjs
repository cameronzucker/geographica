import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('scheduleSourceUpdate coalesces N calls per frame to 1 callback', async () => {
  // Capture rAF callbacks; synthesize one frame.
  let frameCallbacks = [];
  const ctx = {
    requestAnimationFrame: (cb) => { frameCallbacks.push(cb); return frameCallbacks.length; },
    cancelAnimationFrame: () => {},
  };
  const { test: t, ctx: vmCtx } = loadRuler();
  // Override rAF in the loaded ruler's context — done via the loadRuler
  // factory's existing fake, but we want fine-grained control here:
  vmCtx.requestAnimationFrame = ctx.requestAnimationFrame;
  vmCtx.cancelAnimationFrame  = ctx.cancelAnimationFrame;

  let updateCount = 0;
  // Stub refreshMapData via a side-channel: since refreshMapData is internal,
  // we instead instrument scheduleSourceUpdate's behaviour by counting how
  // many times rAF was queued.
  for (let i = 0; i < 10; i++) t.scheduleSourceUpdate();
  // The coalescer must register at most ONE rAF.
  assert.strictEqual(frameCallbacks.length, 1, 'expected 1 rAF call, got ' + frameCallbacks.length);
});

test('scheduleSourceUpdate after frame fires queues a fresh rAF', () => {
  let frameCallbacks = [];
  const { test: t, ctx: vmCtx } = loadRuler();
  vmCtx.requestAnimationFrame = (cb) => { frameCallbacks.push(cb); return frameCallbacks.length; };
  t.scheduleSourceUpdate();
  // Fire the frame
  frameCallbacks[0]();
  // Now schedule another — should queue a NEW rAF.
  t.scheduleSourceUpdate();
  assert.strictEqual(frameCallbacks.length, 2);
});
