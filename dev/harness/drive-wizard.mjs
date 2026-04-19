// Playwright-driven Geographica wizard walkthrough.
// Usage: node drive-wizard.mjs --smoke | --full [--url=http://host:8099]
import { chromium } from 'playwright';

const argv = process.argv.slice(2);
const args = new Set(argv);
const mode = args.has('--full') ? 'full' : 'smoke';
const urlArg = argv.find(a => a.startsWith('--url='));
const baseUrl = urlArg ? urlArg.slice(6) : 'http://localhost:8099';

async function run() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  page.on('console', m => console.log('[browser]', m.text()));
  await page.goto(baseUrl);
  await page.waitForSelector('#step-1');

  // Step 1: accept detected drive, TLS http, advance
  await page.selectOption('#tls-mode', 'http');
  await page.waitForTimeout(500); // debounced validate-path
  await page.click('#btn-next');
  await page.waitForSelector('#step-2');

  // Step 2: Arizona preset + skip detail_imagery
  await page.selectOption('#preset-select', 'arizona');
  await page.click('button.source-btn[data-layer="detail_imagery"][data-value="skip"]');
  await page.click('#btn-next');

  // Step 3: skip credentials (detail_imagery=skip so no creds needed)
  await page.waitForSelector('#step-3');
  await page.click('#btn-skip-creds');

  // Step 4: preflight. Smoke: stop here. Full: run pipeline.
  await page.waitForSelector('#step-4');
  if (mode === 'smoke') {
    console.log('SMOKE: reached Step 4, exiting clean');
    await browser.close();
    return;
  }
  await page.click('#btn-next');
  // Wait up to 8 hours for pipeline_done (realistic for full run)
  await page.waitForSelector('#step-5', { timeout: 8 * 60 * 60 * 1000 });

  // Step 5: wait for all services healthy
  await page.waitForSelector('#completion-msg:not([style*="display:none"])', {
    timeout: 10 * 60 * 1000,
  });
  console.log('FULL: all services healthy');
  await browser.close();
}

run().catch(err => {
  console.error('[drive-wizard] FAIL:', err);
  process.exit(1);
});
