// Contract checks: every JSON Schema compiles (draft 2020-12), examples match their
// expected validity, envelope payloads match their type schema, openapi.yaml is valid 3.1.
const fs = require('fs');
const path = require('path');
const Ajv2020 = require('ajv/dist/2020');
const addFormats = require('ajv-formats');
const { validate } = require('@readme/openapi-parser');

const ROOT = path.resolve(__dirname, '..', '..');
const SCHEMAS = path.join(ROOT, 'schemas');
let failures = 0;
const fail = (m) => { failures++; console.error('FAIL ' + m); };

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) { if (e.name !== 'examples') walk(p); }
    else if (e.name.endsWith('.json')) files.push(p);
  }
})(SCHEMAS);
for (const f of files) {
  const s = JSON.parse(fs.readFileSync(f, 'utf8'));
  const id = path.relative(SCHEMAS, f).split(path.sep).join('/');
  if (s.$id !== id) fail(`${id}: $id is ${s.$id}`);
  ajv.addSchema(s, id);
}
for (const f of files) {
  const id = path.relative(SCHEMAS, f).split(path.sep).join('/');
  try { ajv.getSchema(id); console.log('ok   compile ' + id); } catch (e) { fail(`compile ${id}: ${e.message}`); }
}

const cases = JSON.parse(fs.readFileSync(path.join(SCHEMAS, 'examples', 'cases.json'), 'utf8')).cases;
for (const c of cases) {
  const data = JSON.parse(fs.readFileSync(path.join(SCHEMAS, 'examples', c.example), 'utf8'));
  const v = ajv.getSchema(c.schema);
  let ok = v(data);
  let why = ok ? '' : ajv.errorsText(v.errors);
  if (ok && c.schema === 'events/envelope.json') {
    const pv = ajv.getSchema(`events/${data.type}.json`);
    if (!pv) { ok = false; why = 'no payload schema for ' + data.type; }
    else if (!pv(data.payload)) { ok = false; why = 'payload: ' + ajv.errorsText(pv.errors); }
  }
  if (ok !== c.valid) fail(`${c.example} vs ${c.schema}: expected ${c.valid ? 'valid' : 'invalid'}${why ? ' (' + why + ')' : ''}`);
  else console.log(`ok   ${c.valid ? 'valid  ' : 'invalid'} ${c.example}`);
}

(async () => {
  try {
    await validate(path.join(ROOT, 'api', 'openapi.yaml'));
    console.log('ok   openapi.yaml (OpenAPI 3.1, refs resolved)');
  } catch (e) { fail('openapi.yaml: ' + e.message); }
  if (failures) { console.error(`${failures} failure(s)`); process.exit(1); }
  console.log('all contract checks passed');
})();
