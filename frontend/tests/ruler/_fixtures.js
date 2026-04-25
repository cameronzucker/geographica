import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

// Real haversine for tests that need accurate distances.
export function realHaversine(a, b) {
  const R = 6371000;
  const dLat = (b[1] - a[1]) * Math.PI / 180;
  const dLng = (b[0] - a[0]) * Math.PI / 180;
  const lat1 = a[1] * Math.PI / 180;
  const lat2 = b[1] * Math.PI / 180;
  const sinDLat = Math.sin(dLat / 2);
  const sinDLng = Math.sin(dLng / 2);
  const h = sinDLat*sinDLat + Math.cos(lat1)*Math.cos(lat2)*sinDLng*sinDLng;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// formatDD shim — matches the format app.js's formatDD produces:
// "33.45000° N" (5 decimals + space + hemisphere letter).
export function shimFormatDD(value, dirs) {
  const hemi = value >= 0 ? dirs[0] : dirs[1];
  return Math.abs(value).toFixed(5) + '° ' + hemi;
}

// loadRuler — instantiate ruler.js in a fresh VM context with optional overrides.
// opts: { useImperial?: boolean, fakeDocument?: object, fakeFetch?: function }
export function loadRuler(opts = {}) {
  const win = {
    _haversineDistance: realHaversine,
    _formatDD: shimFormatDD,
    _geographicaUseImperial: opts.useImperial !== undefined ? opts.useImperial : true,
  };
  const doc = opts.fakeDocument || {
    getElementById: () => null,
    addEventListener: () => {},
    createElement: () => ({
      setAttribute: () => {},
      appendChild: () => {},
      addEventListener: () => {},
      classList: { add: () => {}, remove: () => {} },
      style: {},
    }),
  };
  const ctx = {
    window: win,
    document: doc,
    console,
    requestAnimationFrame: (cb) => { setTimeout(cb, 0); return 1; },
    cancelAnimationFrame: () => {},
  };
  if (opts.fakeFetch) ctx.fetch = opts.fakeFetch;
  if (opts.AbortController) ctx.AbortController = opts.AbortController;
  vm.createContext(ctx);
  vm.runInContext(SOURCE, ctx);
  return { ruler: ctx.window._ruler, test: ctx.window._ruler._test, win, ctx };
}
