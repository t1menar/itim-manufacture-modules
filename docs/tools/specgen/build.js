// Build .docx specs from content modules.
// usage: node build.js content/core/*.js [more files...]
// A content module exports { dir, file, meta, blocks }; output goes to docs/<dir>/<file>.
const path = require('path');
const { execFileSync } = require('child_process');
const { build } = require('./lib');
const DOCS = path.resolve(__dirname, '..', '..');
(async () => {
  for (const f of process.argv.slice(2)) {
    const c = require(path.resolve(f));
    const out = path.join(DOCS, c.dir || '', c.file);
    await build(c.meta, c.blocks, out);
    try { execFileSync('zip', ['-d', out, '*/'], { stdio: 'ignore' }); } catch (_) {}
  }
})().catch(e => { console.error(e); process.exit(1); });
