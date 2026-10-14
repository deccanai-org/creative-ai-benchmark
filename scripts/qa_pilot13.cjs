const fs=require('fs');
const path=require('path');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const work=path.resolve(root,'../../reviews/pilot13-refresh-2026-10-14');
const out=path.join(root,'docs/gatsby-v7/annotation-pilot');
const live=process.argv.includes('--live');
const evidence=path.join(work,'qa',live?'live':'');
const ids=Object.keys(JSON.parse(fs.readFileSync(path.join(__dirname,'pilot13_refresh_config.json'))));
const mime={'.ttf':'font/ttf','.png':'image/png','.jpg':'image/jpeg','.svg':'image/svg+xml','.pdf':'application/pdf','.mp4':'video/mp4','.wav':'audio/wav','.txt':'text/plain','.csv':'text/csv'};
(async()=>{
  fs.mkdirSync(evidence,{recursive:true});
  const browser=await chromium.launch({headless:true});
  const context=await browser.newContext({acceptDownloads:true});
  const mappings=new Map();
  const specs=ids.map(id=>JSON.parse(fs.readFileSync(path.join(root,'docs/gatsby-v7/tasks',id,'TASK_SPEC.json'))));
  for(let i=0;i<ids.length;i++)for(const a of specs[i].assets){
    const file=[path.join(work,'upload',ids[i],a.filename),path.join(work,'sources',ids[i],a.filename)].find(p=>fs.existsSync(p));
    assert.ok(file,`${ids[i]} ${a.filename}`);mappings.set(a.public_url,file);
  }
  // Local rendering QA is deliberately isolated from deployment and permission checks.
  if(!live)await context.route('https://annotationprod.s3.ap-south-1.amazonaws.com/**',async route=>{
    const file=mappings.get(route.request().url());assert.ok(file,route.request().url());
    await route.fulfill({path:file,contentType:mime[path.extname(file)]||'application/octet-stream',headers:{'Access-Control-Allow-Origin':'*'}});
  });
  const results=[];
  const page=await context.newPage();
  for(let i=0;i<ids.length;i++){
    const id=ids[i];const errors=[];const listener=e=>errors.push(e.message);page.on('pageerror',listener);
    await page.goto(live?'https://dhigdec.github.io/creative-ai-benchmark/gatsby-v7/annotation-pilot/'+id+'.html':'file://'+path.join(out,id+'.html'),{waitUntil:'domcontentloaded',timeout:60000});
    await page.evaluate(()=>document.querySelectorAll('img').forEach(img=>img.loading='eager'));
    await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(im=>im.decode()));});
    const loaded=await page.evaluate(()=>[...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family));
    assert.ok(loaded.length>0,id);
    for(const width of [1440,720,390]){
      await page.setViewportSize({width,height:1000});
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
      assert.equal(overflow,false,`${id} at ${width}px`);
      if(width===720)await page.locator('.tsys').screenshot({path:path.join(evidence,id+'-typography.png')});
    }
    await page.setViewportSize({width:1440,height:1100});
    await page.screenshot({path:path.join(evidence,id+'-top.png')});
    const dl=page.waitForEvent('download',{timeout:180000});await page.locator('[data-download]').first().click();
    const download=await dl;assert.ok(download.suggestedFilename());assert.equal(await download.failure(),null);
    if(live){
      const font=specs[i].assets.find(a=>a.filename.endsWith('.ttf'));
      const fontDownload=page.waitForEvent('download',{timeout:180000});
      await page.locator('[data-download]').filter({hasText:'Download'}).evaluateAll((links,url)=>links.find(link=>link.href===url).click(),font.public_url);
      assert.equal(await (await fontDownload).failure(),null);
    }
    assert.deepEqual(errors,[]);page.off('pageerror',listener);
    results.push({task:id,fonts_loaded:loaded,asset_tiles:await page.locator('.asset-card').count(),outputs:await page.locator('.output-row').count(),viewports:[1440,720,390],download:download.suggestedFilename(),mode:live?'live GitHub Pages and public S3; font download verified':'local asset interception; does not prove S3 upload'});
    console.log(id,'passed',loaded.join(', '));
  }
  const logos=specs.flatMap((s,i)=>s.assets.filter(a=>a.role==='production identity').map(a=>({id:ids[i],...a})));
  await page.setContent('<style>body{font-family:Arial}main{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}figure{margin:0}img{width:100%;height:240px;object-fit:contain;background:#fff;border:1px solid #ddd}figcaption{font-size:15px}</style><main>'+logos.map(a=>`<figure><img src="${a.public_url}"><figcaption>${a.id}: ${a.filename}</figcaption></figure>`).join('')+'</main>');
  await page.evaluate(async()=>Promise.all([...document.images].map(im=>im.decode())));
  await page.screenshot({path:path.join(evidence,'logos.png'),fullPage:true});
  fs.writeFileSync(path.join(evidence,'render-results.json'),JSON.stringify(results,null,2));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
