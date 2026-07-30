// Convenience wrapper: an AI-news-pipeline RUN → a rendered visual episode.
//
//   node scripts/pipeline/from-run.mjs --run-dir <content-pipeline run dir> [options]
//
// This is the pipeline-AWARE shim for manual/dev use. It knows one pipeline
// convention — orchestration/voiceover_selection.json points at the selected
// voiceover package — resolves the package + its WAV, then hands off to the
// portable, project-agnostic render-episode.mjs. Production triggers
// render-episode.mjs directly (via the orchestration visuals stage); this
// wrapper just saves you from copying paths by hand.
//
// Options (forwarded to render-episode.mjs):
//   --run-dir <path>     REQUIRED. A content-pipeline run directory.
//   --out-dir <path>     where the MP4 goes (default: <run-dir>/visuals)
//   --units <n>          dev slice: only the first n audio units
//   --deterministic      use the no-LLM bridge instead of the DeepSeek art-director
//   --skip-render        stop after build (index.html) — no MP4
//   --out <name>         output basename (default <run_id>-ad)

import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));

const args = process.argv.slice(2);
const opt = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : undefined; };
const has = (n) => args.includes(n);
const die = (msg) => { console.error(msg); process.exit(1); };

const runDirArg = opt("--run-dir");
if (!runDirArg) die("usage: node scripts/pipeline/from-run.mjs --run-dir <content-pipeline run dir> [--out-dir path] [--units n] [--deterministic] [--skip-render] [--out name]");
const runDir = resolve(process.cwd(), runDirArg);
if (!existsSync(runDir)) die(`run dir not found: ${runDir}`);
const runId = basename(runDir).replace(/[^a-z0-9_]+/gi, "_").slice(0, 48);

// The one pipeline convention we depend on: the selected voiceover package.
const selectionPath = resolve(runDir, "orchestration", "voiceover_selection.json");
if (!existsSync(selectionPath)) die(`No voiceover_selection.json in ${runDir}/orchestration — has the voiceover stage completed for this run?`);
const selection = JSON.parse(readFileSync(selectionPath, "utf8"));
const pkgPath = selection.voiceover_package_path;
if (!pkgPath || !existsSync(pkgPath)) die(`Selected voiceover package missing: ${pkgPath}`);
const wavPath = resolve(dirname(pkgPath), "audio", "full_voiceover.wav");
if (!existsSync(wavPath)) die(`Voiceover WAV missing: ${wavPath}`);

const outDir = opt("--out-dir") || resolve(runDir, "visuals");

// Hand off to the portable renderer with explicit paths.
const forward = ["--voiceover-package", pkgPath, "--audio", wavPath, "--out-dir", outDir, "--tag", runId];
if (opt("--out")) forward.push("--out", opt("--out"));
if (opt("--units")) forward.push("--units", opt("--units"));
if (has("--deterministic")) forward.push("--deterministic");
if (has("--skip-render")) forward.push("--skip-render");

execFileSync("node", [resolve(here, "render-episode.mjs"), ...forward], { stdio: "inherit" });
