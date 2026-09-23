// Bundles the frozen Static Recovery v2 port for its two hosts (DECISIONS D-005):
//   dist/worker.js  — Web Worker entry used by the Tauri webview
//   dist/cli.mjs    — Node entry used by ab-cli and CI
// Analysis code is identical; only the transport differs.
import { existsSync } from "node:fs";
import { build } from "esbuild";

const here = new URL(".", import.meta.url).pathname;
if (!existsSync(`${here}src/cli.ts`)) {
  console.log("static-engine: src/cli.ts not present yet; nothing to bundle");
  process.exit(0);
}
await build({ entryPoints: [`${here}src/cli.ts`], bundle: true, platform: "node", format: "esm", target: "node20", outfile: `${here}dist/cli.mjs`, sourcemap: true, logLevel: "info" });
await build({ entryPoints: [`${here}src/worker.ts`], bundle: true, platform: "browser", format: "esm", target: "es2022", outfile: `${here}dist/worker.js`, sourcemap: true, logLevel: "info" });
