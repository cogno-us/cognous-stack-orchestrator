// G3 stage: call the merged G1b Registry profile `run()` (disposable loopback Ganache, ephemeral test key). Development only.
// Usage: node g1b_run.mjs <reportPath> <workDir> <verifierRevision> <evidenceDir|-> ; env: G3_REGISTRY_ROOT, PYTHON, BITREP_ROOT, G1_ROOT.
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [reportPath, workDir, revision, evidenceDir] = process.argv.slice(2);
const profile = await import(pathToFileURL(join(process.env.G3_REGISTRY_ROOT, 'chain', 'g1b', 'profile.mjs')).href);
let handle;
try {
  handle = await profile.run({ reportPath, workDir, revision, evidenceDir: evidenceDir === '-' ? null : evidenceDir });
  const out = { result: handle.result, render: profile.render(handle.result) };
  console.log('G3_G1B_RESULT ' + JSON.stringify(out, (k, v) => (typeof v === 'bigint' ? v.toString() : v)));
} catch (e) {
  console.log('G3_G1B_RESULT ' + JSON.stringify({ error: String(e.message ?? e) }));
  process.exitCode = 3;
} finally {
  if (handle?.close) await handle.close();
}
process.exit(process.exitCode ?? 0);
