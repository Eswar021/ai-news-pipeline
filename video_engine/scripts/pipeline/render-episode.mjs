// Decoupled episode renderer: a voiceover package + its WAV → a rendered MP4.
//
//   node scripts/pipeline/render-episode.mjs \
//     --voiceover-package <path> --audio <path> --out-dir <path> [options]
//
// This is the PORTABLE, project-agnostic entrypoint. It knows nothing about the
// AI-news pipeline (no run dirs, no voiceover_selection.json) — it takes an
// explicit voiceover package + audio file and produces a video in --out-dir.
// Any project that can emit our voiceover-package contract can drive it.
//
// It copies ONLY the two inputs into a local, gitignored .work/<tag>/ (so the
// HyperFrames build can reference the WAV as a local file), runs
// art-director → asset resolver → build → render, then copies the final MP4
// into --out-dir. Nothing is written outside .work/, content/, renders/, and
// --out-dir.
//
// Options:
//   --voiceover-package <path>  REQUIRED. voiceover_package.json (our contract).
//   --audio <path>              WAV. Default: <pkgdir>/audio/full_voiceover.wav,
//                               then <pkgdir>/full_voiceover.wav.
//   --out-dir <path>            REQUIRED. Directory to write the finished MP4 into.
//   --tag <name>                Working/output basename (default: pkg.run_id).
//   --out <name>                Plan/MP4 basename (default: <tag>-ad).
//   --units <n>                 dev slice: only the first n audio units.
//   --deterministic             no-LLM bridge instead of the DeepSeek art-director.
//   --skip-render               stop after build (index.html) — no MP4.

import { readFileSync, existsSync, mkdirSync, copyFileSync, readdirSync, statSync } from "node:fs";
import { dirname, resolve, basename, relative, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..");
const HF = ["--yes", "hyperframes@0.7.68"];

const args = process.argv.slice(2);
const opt = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : undefined; };
const has = (n) => args.includes(n);
const die = (msg) => { console.error(msg); process.exit(1); };

// ---------- inputs ----------
const pkgArg = opt("--voiceover-package");
const outDirArg = opt("--out-dir");
if (!pkgArg || !outDirArg) {
  die("usage: node scripts/pipeline/render-episode.mjs --voiceover-package <path> --out-dir <path> [--audio path] [--tag name] [--out name] [--units n] [--deterministic] [--skip-render]");
}
const pkgPath = resolve(process.cwd(), pkgArg);
if (!existsSync(pkgPath)) die(`voiceover package not found: ${pkgPath}`);
const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
const pkgDir = dirname(pkgPath);

const audioPath = opt("--audio")
  ? resolve(process.cwd(), opt("--audio"))
  : [resolve(pkgDir, "audio", "full_voiceover.wav"), resolve(pkgDir, "full_voiceover.wav")].find(existsSync);
if (!audioPath || !existsSync(audioPath)) {
  die(`voiceover WAV not found (pass --audio). Looked next to the package: ${pkgDir}/audio/full_voiceover.wav`);
}

const tag = (opt("--tag") || pkg.run_id || basename(pkgDir)).replace(/[^a-z0-9_]+/gi, "_").slice(0, 48);
const outName = opt("--out") || `${tag}-ad`;
const outDir = resolve(process.cwd(), outDirArg);

console.log(`Package:  ${pkgPath}`);
console.log(`WAV:      ${audioPath}`);
console.log(`Out dir:  ${outDir}`);

// ---------- 1. stage the two inputs into a local, gitignored working dir ----------
const workDir = resolve(root, ".work", tag);
mkdirSync(workDir, { recursive: true });
copyFileSync(pkgPath, resolve(workDir, "voiceover_package.json"));
copyFileSync(audioPath, resolve(workDir, "full_voiceover.wav"));
const workPkg = `.work/${tag}/voiceover_package.json`;
console.log(`Staged  → ${relative(root, workDir)}/ (voiceover_package.json + full_voiceover.wav)`);

// ---------- 2. run the chain (cwd = video_engine root) ----------
const sh = (cmd, cmdArgs) => execFileSync(cmd, cmdArgs, { cwd: root, stdio: "inherit" });
const planYaml = `content/${outName}.yaml`;
const resolvedYaml = `content/${outName}-resolved.yaml`;

console.log("\n── art-director ──");
if (has("--deterministic")) {
  sh("node", ["scripts/art-director/bridge.mjs", workPkg, "--out", planYaml]);
} else {
  const llmArgs = ["scripts/art-director/llm.mjs", workPkg, "--out", planYaml];
  if (opt("--units")) llmArgs.push("--units", opt("--units"));
  // Format (roundup / deep_dive): roundup gets numbered story dividers; a deep-dive
  // is one continuous topic. Absent → the engine defaults (roundup-style).
  if (opt("--format")) llmArgs.push("--format", opt("--format"));
  if (opt("--channel-name")) llmArgs.push("--channel-name", opt("--channel-name"));
  if (opt("--channel-handle")) llmArgs.push("--channel-handle", opt("--channel-handle"));
  // Optional real source imagery: the pipeline's asset manifest (og:image per
  // selected story). Absent → the engine plans exactly as before (decoupled).
  if (opt("--asset-manifest")) llmArgs.push("--asset-manifest", resolve(process.cwd(), opt("--asset-manifest")));
  sh("node", llmArgs);
}

console.log("\n── asset resolver ──");
sh("node", ["scripts/art-director/resolve-assets.mjs", planYaml, "--out", resolvedYaml]);

console.log("\n── build ──");
sh("node", ["scripts/build.mjs", resolvedYaml]);

if (has("--skip-render")) {
  console.log(`\n✓ Built index.html from ${resolvedYaml} (render skipped).`);
  process.exit(0);
}

console.log("\n── render ──");
const rendersDir = resolve(root, "renders");
const before = renderMp4s();
sh("npx", [...HF, "render"]);

// ---------- 3. deliver the newest MP4 into --out-dir ----------
const after = renderMp4s();
const fresh = after.filter((f) => !before.some((b) => b.path === f.path) || f.mtime > (before.find((b) => b.path === f.path)?.mtime ?? 0));
const newest = (fresh.length ? fresh : after).sort((a, b) => b.mtime - a.mtime)[0];
if (!newest) die("render finished but no MP4 was found in renders/");
mkdirSync(outDir, { recursive: true });
const dest = resolve(outDir, `${outName}.mp4`);
copyFileSync(newest.path, dest);
console.log(`\n✓ Episode → ${dest}`);

function renderMp4s() {
  if (!existsSync(rendersDir)) return [];
  return readdirSync(rendersDir)
    .filter((f) => f.toLowerCase().endsWith(".mp4"))
    .map((f) => { const p = join(rendersDir, f); return { path: p, mtime: statSync(p).mtimeMs }; });
}
