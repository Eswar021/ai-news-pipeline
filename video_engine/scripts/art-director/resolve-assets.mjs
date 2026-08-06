// Asset resolver pass.
//
//   node scripts/art-director/resolve-assets.mjs <scene.yaml> [--out <path>]
//
// Runs AFTER the art-director, BEFORE build.mjs. Walks the scene plan and fills in
// real media the art-director asked for BY DESCRIPTION:
//   - Brand components name a company ENTITY  → official logo   (media-use --type logo)
//   - Real-media components give an image QUERY → a photo         (media-use --type image)
// The LLM only ever names/describes; this pass fetches the file and injects the path.
// LLM judgment, code plumbing.
//
// Resolution is a BUILD-time step (like the LLM call): media-use freezes files
// locally, so the render stays deterministic. On failure the path param is left
// UNSET so the component falls back to its own default (text form for Brand,
// placeholder image for real-media) — never a broken image.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import yaml from "js-yaml";

const here = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(here, "..", "..");
const MEDIA_USE = "/Users/manikantamb/.claude/skills/media-use/scripts/resolve.mjs";
// media-use's image/bgm path shells out to the `heygen` CLI in ~/.local/bin — make
// sure it's on PATH (logos don't need it). Keep the system dirs to avoid clobbering.
const home = process.env.HOME || "";
const MEDIA_ENV = { ...process.env, PATH: `/usr/bin:/bin:/usr/local/bin:${home}/.local/bin:${process.env.PATH || ""}` };

// component -> { type, fields: { <param the LLM sets>: <param to fill with the file> } }
const RESOLVE = {
  "entity-intro": { type: "logo", fields: { entity: "logo" } },
  "logo-vs-logo": { type: "logo", fields: { leftEntity: "leftLogo", rightEntity: "rightLogo" } },
  "logo-reveal": { type: "logo", fields: { entity: "logo" } },
  "logo-wall": { type: "logo", arrayFields: { entities: "logos" } }, // list of entities -> list of logo paths
  "attribution": { type: "logo", fields: { entity: "logo" } },
  "photo": { type: "image", fields: { query: "src" } },
  "browser-frame": { type: "image", fields: { query: "src" } },
  "image-reveal": { type: "image", fields: { query: "src" } },
  "spotlight": { type: "image", fields: { query: "src" } },
  "image-compare": { type: "image", fields: { beforeQuery: "beforeSrc", afterQuery: "afterSrc" } },
  "image-grid": { type: "image", arrayFields: { queries: "srcs" } },
  "parallax": { type: "image", fields: { query: "src" } },
  "pip": { type: "image", fields: { mainQuery: "mainSrc", pipQuery: "pipSrc" } },
};

const args = process.argv.slice(2);
const inArg = args.find((a) => !a.startsWith("--"));
const opt = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : undefined; };
if (!inArg) { console.error("usage: node scripts/art-director/resolve-assets.mjs <scene.yaml> [--out <path>]"); process.exit(1); }
const inPath = resolve(process.cwd(), inArg);
const outPath = resolve(process.cwd(), opt("--out") || inPath.replace(/\.ya?ml$/, "-resolved.yaml"));

const doc = yaml.load(readFileSync(inPath, "utf8")) || {};
const scenes = Array.isArray(doc.scenes) ? doc.scenes : [];

const cache = new Map();
function resolveAsset(type, value) {
  const v = String(value || "").trim();
  const key = type + ":" + v.toLowerCase();
  if (!v) return "";
  if (cache.has(key)) return cache.get(key);
  let path = "";
  try {
    // A real source-image URL (from the pipeline's asset manifest) is FROZEN
    // exactly via --from; a plain description is a stock search via --intent.
    const isUrl = /^https?:\/\//i.test(v);
    const muArgs = type === "logo"
      ? ["--type", "logo", "--entity", v, "--intent", `${v} logo`, "--project", ".", "--json"]
      : isUrl
        ? ["--type", "image", "--from", v, "--project", ".", "--json"]
        : ["--type", "image", "--intent", v, "--project", ".", "--json"];
    const out = execFileSync("node", [MEDIA_USE, ...muArgs],
      { cwd: projectRoot, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], env: MEDIA_ENV });
    const j = JSON.parse(out);
    if (j && j.ok && j.path) path = j.path;
    if (type === "logo" && /\.ico$/i.test(path)) path = ""; // favicon = media-use's last resort = "no real logo"
  } catch { path = ""; }
  cache.set(key, path);
  return path;
}

function resolveLayer(ly) {
  const spec = RESOLVE[ly.component];
  if (!spec || !ly.params) return;
  // single-value fields (entity → logo, query → src)
  for (const [srcParam, dstParam] of Object.entries(spec.fields || {})) {
    const val = ly.params[srcParam];
    if (!val) continue;
    const p = resolveAsset(spec.type, val);
    if (p) ly.params[dstParam] = p; // only on success; failure → component default (text / placeholder)
    process.stderr.write(p ? `  ${spec.type}: ${val} → ${p}\n` : `  ${spec.type}: ${val} → (unresolved, fallback)\n`);
  }
  // array fields (entities[] → logos[]); parallel list, "" where unresolved (component text-cell fallback)
  for (const [srcParam, dstParam] of Object.entries(spec.arrayFields || {})) {
    const list = ly.params[srcParam];
    if (!Array.isArray(list) || !list.length) continue;
    ly.params[dstParam] = list.map((v) => {
      const p = v ? resolveAsset(spec.type, v) : "";
      process.stderr.write(`  ${spec.type}[]: ${v} → ${p || "(text cell)"}\n`);
      return p;
    });
  }
}

let count = 0;
for (const sc of scenes) {
  const layers = Array.isArray(sc.layers) ? sc.layers : [sc];
  for (const ly of layers) { if (RESOLVE[ly.component]) { resolveLayer(ly); count++; } }
}

// Safety net: an image-primary component with NO resolved image renders blank. Never
// ship a blank slide — fall back to a text card built from its caption/label/query.
// (A miss usually means media-use image resolution is unavailable, e.g. heygen not
// authenticated; real-URL browser-frames are unaffected and keep their image.)
const IMG_PRIMARY = { photo: "src", parallax: "src", "image-reveal": "src", spotlight: "src", "image-compare": "afterSrc", "image-grid": "srcs", pip: "mainSrc" };
const cleanTxt = (s) => String(s || "").replace(/\s+/g, " ").trim();
let recovered = 0;
for (const sc of scenes) {
  if (Array.isArray(sc.layers)) continue; // layered scenes carry their own base content
  const key = IMG_PRIMARY[sc.component];
  if (!key || !sc.params) continue;
  const has = key === "srcs"
    ? (Array.isArray(sc.params.srcs) && sc.params.srcs.some(Boolean))
    : !!sc.params[key];
  if (has) continue;
  const p = sc.params;
  const text = cleanTxt(p.caption || p.afterLabel || p.beforeLabel || (p.query || p.afterQuery || p.mainQuery || "").split(",")[0]).slice(0, 110);
  sc.component = "kinetic-sentence";
  sc.params = { text };
  recovered++;
  process.stderr.write(`  unresolved image → text fallback ("${text.slice(0, 40)}")\n`);
}
if (recovered) console.log(`Recovered ${recovered} unresolved image scene(s) as text (no blank slides).`);

writeFileSync(outPath, `# Asset-resolved from ${relative(projectRoot, inPath)} — ${count} asset scene(s), ${cache.size} unique lookups.\n` + yaml.dump(doc, { lineWidth: 100 }));
console.log(`Resolved ${count} asset scene(s), ${cache.size} lookups → ${relative(projectRoot, outPath)}`);
