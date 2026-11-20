// PAR-10-T2 module harness: exercise the compiled releaseIntegrity module
// against a real or synthetic install tree. Exit code 0 = accepted.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [modulePath, installRoot, expectedJson] = process.argv.slice(2);
if (!modulePath || !installRoot) {
  console.error('usage: node verify-harness.mjs <compiled releaseIntegrity.js> <installRoot> [expectedJson]');
  process.exit(2);
}
const expected = expectedJson ? JSON.parse(expectedJson) : {};
const { verifyReleaseIntegrity } = await import(pathToFileURL(path.resolve(modulePath)).href);
const report = verifyReleaseIntegrity({ installRoot: path.resolve(installRoot), expected });
console.log(JSON.stringify({
  ok: report.ok,
  manifestPath: report.manifestPath,
  manifest_app_version: report.manifest?.app_version,
  manifest_has_installer: report.manifest ? Object.hasOwn(report.manifest, 'installer') : null,
  verifiedArtifacts: report.verifiedArtifacts,
  issues: report.issues.map(({ code, field, path: issuePath, expected: wanted, actual }) => ({
    code, field, path: issuePath, expected: wanted, actual,
  })),
}, null, 2));
process.exit(report.ok ? 0 : 1);