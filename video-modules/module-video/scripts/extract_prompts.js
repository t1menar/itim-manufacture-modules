// Copies the runtime prompts of docs/module-video/module-video-06-prompts (sections 2 to 7 and 9) verbatim
// into prompts/<step>/1.0.0/ (CLAUDE.md, task.md, meta.json) and prompts/skill/1.0.0/SKILL.md.
// Run from module-video/:  node scripts/extract_prompts.js
const fs = require('fs');
const path = require('path');
const SRC = path.join(__dirname, '../../../docs/tools/specgen/content/module-video/module-video-06-prompts.js');
const doc = require(SRC);
const out = path.join(__dirname, '../prompts');
const blocks = doc.blocks;
const text = (s) => s.replace(/`/g, '');
let step = null, section = null;
const found = {};
function ensure(name) { return (found[name] = found[name] || { meta: {} }); }
for (const b of blocks) {
  if (b[0] === 'h1') {
    const m = b[1].match(/^\d+\. ([a-z-]+)@(\d+\.\d+\.\d+)/);
    step = m ? m[1] : (b[1].startsWith('2. Shared skill') ? 'skill' : null);
    if (step) ensure(step).version = m ? m[2] : '1.0.0';
    section = null;
    continue;
  }
  if (!step) continue;
  if (b[0] === 'h2') { section = b[1].replace(/^\d+\.\d+ /, ''); continue; }
  const s = ensure(step);
  if (b[0] === 'table' && b[1][0] === 'Item') {
    for (const [k, v] of b[2]) s.meta[k] = v;
  }
  if (b[0] === 'code') {
    if (step === 'skill') s.skill = b[1];
    else if (section === 'CLAUDE.md') s.claude = b[1];
    else if (section === 'Task template') s.task = b[1];
  }
}
let n = 0;
for (const [name, s] of Object.entries(found)) {
  if (name === 'skill') {
    const d = path.join(out, 'skill', '1.0.0'); fs.mkdirSync(d, { recursive: true });
    fs.writeFileSync(path.join(d, 'SKILL.md'), s.skill + '\n'); n++; continue;
  }
  if (!s.claude || !s.task) continue;
  const d = path.join(out, name, s.version); fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, 'CLAUDE.md'), s.claude + '\n');
  fs.writeFileSync(path.join(d, 'task.md'), s.task + '\n');
  const ph = [...new Set([...s.task.matchAll(/\{([a-z_]+)\}/g)].map((m) => m[1]))].sort();
  const meta = {
    id: `${name}@${s.version}`, step: name, version: s.version, placeholders: ph,
    declared_placeholders: (s.meta['Placeholders'] || '').match(/\{([a-z_]+)\}/g)?.map((x) => x.slice(1, -1)) || [],
    input_files: text(s.meta['Input files'] || ''), output: text(s.meta['Output'] || ''),
    done_when: text(s.meta['Done when'] || ''), tools_network: text(s.meta['Tools / network'] || ''),
  };
  fs.writeFileSync(path.join(d, 'meta.json'), JSON.stringify(meta, null, 1) + '\n'); n++;
}
console.log(`wrote ${n} prompt directories to ${out}`);
