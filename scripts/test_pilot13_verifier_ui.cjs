const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const base = process.env.PILOT_BASE || `file://${root}/docs/gatsby-v7/`;
const out = path.resolve(root, '../../reviews/pilot13-verifier-lock-2026-10-22');
const ids = Object.keys(JSON.parse(fs.readFileSync(path.join(__dirname,'pilot13_refresh_config.json'))));
async function main() {
  fs.mkdirSync(out,{recursive:true});
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:960}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'annotation-pilot/measurement-guide.html');
    await page.locator('#neutral-form button').click();
    assert.match(await page.locator('#neutral-result').innerText(),/^Yes/);
    await page.locator('#red').fill('0');
    await page.locator('#neutral-form button').click();
    assert.match(await page.locator('#neutral-result').innerText(),/^No/);
    const fixture=await page.evaluate(()=>{
      const canvas=document.createElement('canvas');canvas.width=10;canvas.height=10;
      const c=canvas.getContext('2d');c.fillStyle='#ffffff';c.fillRect(0,0,10,10);const mask=canvas.toDataURL().split(',')[1];
      c.fillStyle='#323c46';c.fillRect(0,0,5,1);return{mask,art:canvas.toDataURL().split(',')[1]};
    });
    for(const [id,key] of [['art','art'],['mask','mask']]) await page.locator('#'+id).setInputFiles({name:key+'.png',mimeType:'image/png',buffer:Buffer.from(fixture[key],'base64')});
    await page.locator('#colours').fill('#323C46');await page.locator('#area-button').click();
    await page.waitForFunction(()=>document.getElementById('area-result').textContent.startsWith('Yes:'));
    assert.match(await page.locator('#area-result').innerText(),/5 matching pixels \/ 100/);
    for(const width of [1280,390]) {
      await page.setViewportSize({width,height:960});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:path.join(out,`measurement-guide-${width}.png`),fullPage:true});
    }
    const coverage=[];
    for(const id of ids) {
      await page.goto(base+`annotation-pilot/coverage/${id}.html`);
      await page.locator('details.deliv').first().evaluate(e=>e.open=true);
      const text=await page.locator('details.deliv').first().innerText();
      assert.match(text,/Auto verifiers/);assert.match(text,/Human verifiers/);
      assert.match(text,/unique checks/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,id);
      coverage.push(id);
    }
    await page.setViewportSize({width:1280,height:960});
    await page.goto(base+'annotation-pilot/coverage/PHOTO-20.html');
    await page.screenshot({path:path.join(out,'coverage-photo20.png')});
    await page.goto(base+'index.html#PHOTO-19/human',{waitUntil:'domcontentloaded',timeout:120000});
    assert.equal(await page.locator('#current-scoring-policy').count(),1);
    assert.match(await page.locator('#current-scoring-policy').innerText(),/excluded from the score denominator/);
    assert.match(await page.locator('#content').innerText(),/within 5 in every RGB channel/);
    await page.screenshot({path:path.join(out,'main-human.png')});
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'browser-check.json'),JSON.stringify({base,coverage,calculatorChecks:3,viewports:[1280,390],errors},null,2));
    console.log('13 coverage pages, main Human tab, responsive guide and three calculator interactions passed.');
  } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
