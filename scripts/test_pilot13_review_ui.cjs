const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const live = process.argv.includes('--live');
const base = live ? 'https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/' : `file://${root}/docs/gatsby-v7/`;
const out = path.resolve(root, '../../reviews/pilot13-followup-2026-10-22', live ? 'live' : 'local');
const ids = Object.keys(JSON.parse(fs.readFileSync(path.join(__dirname, 'pilot13_refresh_config.json'))));

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    for (const id of ids) {
      await page.goto(`${base}annotation-pilot/${id}.html`, {waitUntil: 'domcontentloaded', timeout: 120000});
      assert.equal(await page.locator('script[src*="@iframe-resizer/child@5"]').count(), 1, id);
      assert.ok(await page.locator('.tsys').count(), id);
      for (const width of [1440, 390]) {
        await page.setViewportSize({width, height: 1000});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${id} overflow`);
      }
      if (id === 'LAYOUT-12') {
        await page.setViewportSize({width: 1440, height: 1000});
        await page.locator('.tsys').screenshot({path: path.join(out, 'layout12-type.png')});
        assert.ok((await page.locator('.tsys').innerText()).includes('Remaining act names are 48 pt'));
      }
    }
    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto(`${base}index.html#PHOTO-28`, {waitUntil: 'domcontentloaded', timeout: 180000});
    for (const id of ids) {
      await page.locator(`[data-task="${id}"]`).click();
      await page.getByRole('tab', {name: 'Human verifiers', exact: true}).click();
      const spec = JSON.parse(fs.readFileSync(`${root}/docs/gatsby-v7/tasks/${id}/TASK_SPEC.json`));
      await page.waitForFunction(n => document.querySelectorAll('#content .checking-method').length === n, spec.verifiers_human.length);
      assert.equal(await page.locator('#content .checking-method').count(), spec.verifiers_human.length, id);
      const guidance = await page.locator('#content .checking-method').allTextContents();
      assert.ok(guidance.every(text => /^(Look|Measure|Estimate): \S/.test(text)), id);
      assert.equal(await page.locator('#content [title*="/A0"]').count(), 0, `${id} auto mixed into human tab`);
      if (id === 'PHOTO-28') {
        const row = page.locator('tr').filter({has: page.locator('[title="PHOTO-28/booking-story/H001"]')});
        assert.ok((await row.innerText()).includes('Measure:'));
        await row.screenshot({path: path.join(out, 'measurement-guidance.png')});
        await page.setViewportSize({width: 390, height: 900});
        await row.screenshot({path: path.join(out, 'measurement-mobile.png')});
        await page.setViewportSize({width: 1440, height: 1000});
      }
      console.log(`${id}: brief and ${guidance.length} human methods rendered`);
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
