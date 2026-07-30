// Component gallery builder.
//
//   node scripts/gallery.mjs [--only <family>]
//
// Renders ONE clean snapshot of every registered component into gallery/<family>/,
// builds a per-family contact sheet, and writes gallery/README.md — so the whole
// component library can be inspected in one place. Re-run anytime after adding/editing
// components. Uses representative params from scripts/gallery-params.yaml (falls back to
// each component's own defaults).

import { readFileSync, writeFileSync, mkdirSync, rmSync, existsSync, readdirSync, renameSync } from "node:fs";
import { dirname, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import yaml from "js-yaml";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const HF = ["--yes", "hyperframes@0.7.68"];
const FF = "/opt/homebrew/bin/ffmpeg";
const home = process.env.HOME || "";
const ENV = { ...process.env, PATH: `/usr/bin:/bin:/usr/local/bin:${home}/.local/bin:${process.env.PATH || ""}` };

const onlyFamily = (() => { const i = process.argv.indexOf("--only"); return i >= 0 ? process.argv[i + 1] : null; })();

const reg = yaml.load(readFileSync(resolve(root, "content/registry.yaml"), "utf8")) || {};
const params = yaml.load(readFileSync(resolve(here, "gallery-params.yaml"), "utf8")) || {};
const components = reg.components || {};

const galleryDir = resolve(root, "gallery");
const workDir = resolve(galleryDir, "_work");
mkdirSync(workDir, { recursive: true });

const sh = (cmd, args, opts = {}) => execFileSync(cmd, args, { cwd: root, stdio: ["ignore", "ignore", "ignore"], env: ENV, ...opts });

const byFamily = {};
const names = Object.keys(components).filter((c) => !onlyFamily || (components[c].family === onlyFamily));

let ok = 0;
for (const comp of names) {
  const family = components[comp].family || "misc";
  (byFamily[family] ||= []).push(comp);
  const p = params[comp] || {};
  const content = { scenes: [{ component: comp, duration: 4, params: p }] };
  writeFileSync(resolve(workDir, "content.yaml"), yaml.dump(content, { lineWidth: 120 }));
  try {
    sh("node", [resolve(here, "art-director/resolve-assets.mjs"), "gallery/_work/content.yaml", "--out", "gallery/_work/content-resolved.yaml"]);
    sh("node", [resolve(here, "build.mjs"), "gallery/_work/content-resolved.yaml"]);
    const shotDir = resolve(workDir, "shot");
    rmSync(shotDir, { recursive: true, force: true });
    sh("npx", [...HF, "snapshot", "--at", "3", "--no-end", "--timeout", "20000", "-o", "gallery/_work/shot"]);
    const png = readdirSync(shotDir).find((f) => f.endsWith(".png"));
    if (!png) throw new Error("no snapshot");
    const famDir = resolve(galleryDir, family);
    mkdirSync(famDir, { recursive: true });
    renameSync(resolve(shotDir, png), resolve(famDir, `${comp}.png`));
    ok++;
    process.stderr.write(`  ✓ ${family}/${comp}\n`);
  } catch (e) {
    process.stderr.write(`  ✗ ${comp} — ${String(e.message).slice(0, 80)}\n`);
  }
}

// per-family contact sheets (uniform 16:9 tiles → robust `tile` filter)
const pad = (n) => String(n).padStart(3, "0");
for (const [family, comps] of Object.entries(byFamily)) {
  const pics = comps.slice().sort().map((c) => resolve(galleryDir, family, `${c}.png`)).filter(existsSync);
  if (!pics.length) continue;
  const seqDir = resolve(workDir, "seq");
  rmSync(seqDir, { recursive: true, force: true });
  mkdirSync(seqDir, { recursive: true });
  pics.forEach((p, i) => sh(FF, ["-y", "-i", p, "-vf", "scale=560:315", resolve(seqDir, `s_${pad(i)}.png`)]));
  const cols = Math.min(3, pics.length);
  const rows = Math.ceil(pics.length / cols);
  try {
    sh(FF, ["-y", "-start_number", "0", "-i", resolve(seqDir, "s_%03d.png"),
      "-vf", `tile=${cols}x${rows}:padding=10:margin=10:color=0x0b0e14`, "-frames:v", "1", resolve(galleryDir, `_${family}.jpg`)]);
  } catch { process.stderr.write(`  (contact sheet skipped for ${family})\n`); }
}

// index
const order = ["typography", "data", "diagrams", "real-media", "source", "brand", "glue"];
const fams = Object.keys(byFamily).sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
let md = `# Component gallery\n\nOne snapshot per component. Regenerate: \`node scripts/gallery.mjs\`.\nAsset components (logos/photos) use real resolved media; others use representative or default params.\n\n`;
for (const f of fams) {
  md += `## ${f} (${byFamily[f].length})\n\n`;
  for (const c of byFamily[f].sort()) md += `- **${c}** — ![${c}](${f}/${c}.png)\n`;
  md += `\n`;
}
md += `\n> Transitions (crossfade · dip · push · whip · zoom) are runner-level, not standalone components — see \`content/glue-demo.yaml\`.\n`;
writeFileSync(resolve(galleryDir, "README.md"), md);

rmSync(workDir, { recursive: true, force: true });
console.log(`Gallery: ${ok}/${names.length} components → ${relative(root, galleryDir)}/ (per-family PNGs + _<family>.jpg sheets + README.md)`);
