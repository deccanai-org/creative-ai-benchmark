const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const os = require('node:os');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');
const run = promisify(execFile);

const root = path.resolve(__dirname, '..');
const work = path.resolve(root, '../../reviews/pilot13-refresh-2026-10-14');
const ids = Object.keys(JSON.parse(fs.readFileSync(path.join(__dirname, 'pilot13_refresh_config.json'))));
const assets = ids.flatMap(id => JSON.parse(fs.readFileSync(path.join(root, 'docs/gatsby-v7/tasks', id, 'ASSET_MANIFEST.json'))).map(asset => ({task: id, ...asset})));
const prefix = 'https://annotationprod.s3.ap-south-1.amazonaws.com/creative-ai-benchmark/v3.1/pilot-refresh-2026-10-14/';
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

(async () => {
  const results = [];
  let next = 0;
  async function worker() {
    while (next < assets.length) {
      const asset = assets[next++];
      const refreshed = asset.public_url.startsWith(prefix);
      const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pilot-asset-check-'));
      try {
        const target = path.join(temp, 'asset');
        const args = ['--globoff', '--silent', '--show-error', '--fail', '--max-time', '30',
          '-H', 'Origin: https://dhigdec.github.io', '-o', target,
          '-w', '{"status":%{http_code},"headers":%{header_json}}'];
        if (!refreshed) args.push('--head');
        args.push(asset.public_url);
        const {stdout} = await run('curl', args, {maxBuffer: 1024 * 1024});
        const response = JSON.parse(stdout);
        assert.equal(response.status, 200, `HTTP ${response.status}`);
        const cors = response.headers['access-control-allow-origin']?.[0];
        assert.ok(cors === '*' || cors === 'https://dhigdec.github.io', 'Missing browser CORS');
        let sha256;
        if (refreshed) {
          const bytes = fs.readFileSync(target);
          sha256 = digest(bytes);
          const local = fs.readFileSync(path.join(work, 'upload', asset.task, asset.filename));
          assert.equal(sha256, digest(local), 'Uploaded file differs from local original');
          if (asset.sha256) assert.equal(sha256, asset.sha256, 'Manifest hash mismatch');
        }
        results.push({task: asset.task, filename: asset.filename, url: asset.public_url, refreshed, status: 200, cors, sha256});
      } catch (error) {
        results.push({task: asset.task, filename: asset.filename, refreshed, error: error.message});
      } finally {
        fs.rmSync(temp, {recursive: true, force: true});
      }
      if (results.length % 40 === 0) console.log(`${results.length}/${assets.length} asset checks completed`);
    }
  }
  await Promise.all(Array.from({length: 8}, worker));
  const failures = results.filter(r => r.error);
  const summary = {
    revision: 'pilot13_inputs_2026_10_14', verified_at: new Date().toISOString(),
    task_count: ids.length, asset_entries: results.length,
    public_access_verified: results.filter(r => r.status === 200).length,
    refreshed_assets_hash_verified: results.filter(r => r.refreshed && r.sha256).length,
    browser_origin: 'https://dhigdec.github.io', failures: failures.length,
  };
  fs.writeFileSync(path.join(work, 'public-asset-verification.json'), JSON.stringify({...summary, results}, null, 2) + '\n');
  assert.equal(failures.length, 0, JSON.stringify(failures));
  assert.equal(summary.refreshed_assets_hash_verified, 73);
  fs.writeFileSync(path.join(root, 'docs/gatsby-v7/annotation-pilot/asset-access-status.json'), JSON.stringify(summary, null, 2) + '\n');
  console.log(JSON.stringify(summary));
})().catch(error => { console.error(error.message); process.exitCode = 1; });
