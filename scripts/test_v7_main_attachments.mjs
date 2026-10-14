import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const site = path.join(repo, 'docs/gatsby-v7');
const html = fs.readFileSync(path.join(site, 'index.html'), 'utf8');
const dataMarker = '<script type="application/json" id="data">';
const scriptMarker = '</script><script>const data=';
const attachmentMarker = '</script><script src="pilot-2026-09-28/main-page-attachments.js"';
const rawData = html.split(dataMarker)[1]?.split('</script>')[0];
const scriptStart = html.indexOf(scriptMarker);
const scriptEnd = html.indexOf(attachmentMarker, scriptStart);
assert.ok(rawData && scriptStart >= 0 && scriptEnd > scriptStart);

const elements = new Map();
const document = {
  getElementById(id) {
    if (!elements.has(id)) {
      elements.set(id, id === 'data'
        ? { textContent: rawData }
        : { innerHTML: '', value: '', addEventListener() {} });
    }
    return elements.get(id);
  },
};
const context = vm.createContext({ document, location: { hash: '#PHOTO-04' }, history: { replaceState() {} } });
vm.runInContext(html.slice(scriptStart + '</script><script>'.length, scriptEnd), context, { timeout: 30000 });
vm.runInContext(fs.readFileSync(path.join(site, 'pilot-2026-09-28/main-page-attachments.js'), 'utf8'), context, { timeout: 30000 });

const expected = new Map([
  ['PHOTO-04', [4, 17, 17]],
  ['PHOTO-06', [18, 63, 63]],
  ['PHOTO-08', [7, 28, 28]],
  ['PHOTO-10', [12, 48, 48]],
  ['PHOTO-19', [19, 76, 76]],
  ['PHOTO-20', [16, 0, 112]],
  ['PHOTO-24', [7, 29, 29]],
  ['PHOTO-26', [2, 10, 10]],
  ['PHOTO-28', [3, 12, 12]],
  ['LAYOUT-15', [14, 0, 159]],
]);

for (const [id, [outputCount, passed, total]] of expected) {
  vm.runInContext(`current=data.tasks.find(task=>task.id==='${id}');section='Outputs';render();`, context);
  const outputs = document.getElementById('content').innerHTML;
  assert.equal((outputs.match(/class="output-card"/g) || []).length, outputCount, id);
  assert.ok(outputs.includes(`pilot-2026-09-28/runs/${id}/deliverables/`), id);
  assert.ok(outputs.includes(`pilot-2026-09-28/runs/${id}/thumbnails/`), id);

  vm.runInContext(`section='Auto verifiers';render();`, context);
  const auto = document.getElementById('content').innerHTML;
  assert.ok(auto.includes(`${total} current checks: not assessed`), id);
  assert.equal(vm.runInContext('current.run.verifier_summary.automatic_passed',context),passed);
  assert.equal(vm.runInContext('current.checks.filter(c=>c.type==="auto"&&c.status==="passed").length',context),0);

  vm.runInContext(`section='Trajectory verifiers';render();`, context);
  const trajectory = document.getElementById('content').innerHTML;
  assert.ok(trajectory.includes('class="trajectory-step"'), id);
  assert.ok(trajectory.includes(`pilot-2026-09-28/runs/${id}/trajectory.html`), id);
  console.log(`${id}: ${outputCount} files, ${passed}/${total} auto checks recorded passed, trajectory visible`);
}
