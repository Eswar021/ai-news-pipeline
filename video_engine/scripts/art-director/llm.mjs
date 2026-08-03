// LLM art-director (v1).
//
//   node scripts/art-director/llm.mjs <voiceover_package.json> [options]
//
// Reads the upstream voiceover_package.json and asks DeepSeek (V4 Pro, thinking
// enabled, reasoning_effort max) to author OUR scene plan — choosing components
// from component-menu.yaml, writing CONCISE on-screen copy, and splitting long
// beats into 2-3 shots. One LLM call per audio unit (intro / each story / closing).
//
// TIMING IS NEVER TRUSTED TO THE LLM: the model proposes shots + relative weights;
// this code allocates each beat's AUTHORITATIVE voiceover duration across its shots
// and guarantees full beat coverage (deterministic fallback for any missed beat).
// It ignores upstream visual_goal/visual_brief by design.
//
// Options:
//   --out <path>       output YAML (default: content/<run>-ad.yaml)
//   --audio <path>     master WAV (default: full_voiceover.wav next to the package)
//   --units <n>        only plan the first n audio units (dev / cost control)
//   --start <n>        first unit index to plan (0-based; default 0)
//   --dry-run          print prompts + skip API calls

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve, relative, basename } from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "js-yaml";

const here = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(here, "..", "..");

// ---------- args ----------
const args = process.argv.slice(2);
const pkgArg = args.find((a) => !a.startsWith("--"));
const opt = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : undefined; };
const has = (n) => args.includes(n);
if (!pkgArg) {
  console.error("usage: node scripts/art-director/llm.mjs <voiceover_package.json> [--out ..] [--audio ..] [--units n] [--start n] [--dry-run]");
  process.exit(1);
}
const pkgPath = resolve(process.cwd(), pkgArg);
const unitsLimit = opt("--units") ? Number(opt("--units")) : Infinity;
const startUnit = opt("--start") ? Number(opt("--start")) : 0;
const dryRun = has("--dry-run");

// ---------- config + menu + env ----------
const cfg = yaml.load(readFileSync(resolve(here, "config.yaml"), "utf8")) || {};
const menu = yaml.load(readFileSync(resolve(here, "component-menu.yaml"), "utf8")) || {};
const validComponents = new Set(Object.keys(menu.components || {}));
const validTransitions = new Set(menu.transitions || []);
const componentParams = Object.fromEntries(Object.entries(menu.components || {}).map(([k, v]) => [k, v.params || []]));
// optional single-line text params: if the LLM omits one, pass "" so the component
// HIDES it (with key-present-wins get()) instead of showing a stale default.
const BLANKABLE = new Set(["subtitle", "kicker", "caption", "eyebrow", "sublabel", "author", "role", "secondary", "center", "title", "label", "tagline"]);

// Channel identity is a FACT, not an LLM choice — inject the real values into
// brand components so the model can never invent a handle. Config default, with
// per-run overrides from the pipeline's channel_name.
const brandCfg = cfg.brand || {};
const channel = {
  name: opt("--channel-name") || brandCfg.name || "The AI Dungeon",
  handle: opt("--channel-handle") || brandCfg.handle || "@TheAIDungeon",
};
channel.kicker = (brandCfg.kicker || channel.name).toUpperCase();
const CHANNEL_PARAM = { outro: ["handle", channel.handle], watermark: ["text", channel.handle], "episode-open": ["kicker", channel.kicker] };

function loadApiKey() {
  const name = cfg.api_key_env || "DEEPSEEK_API_KEY";
  if (process.env[name]) return process.env[name];
  const envFile = resolve(projectRoot, cfg.env_file || "../../AI_Content_Creation/.env");
  if (existsSync(envFile)) {
    for (const line of readFileSync(envFile, "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (m && m[1] === name) return m[2].replace(/^["']|["']$/g, "");
    }
  }
  throw new Error(`${name} not found in environment or ${cfg.env_file}`);
}

// ---------- text helpers ----------
const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
const firstSentence = (t) => clean(t).split(/(?<=[.!?])\s+/)[0] || clean(t);

// ---------- source imagery (optional pipeline asset manifest) ----------
// Real og:image per selected story. We GUARANTEE each story unit shows its real
// source image at least once — even when the LLM plan for that unit fails and
// falls back to text — so episodes are never wall-to-wall text cards. The image
// component's query is set to the exact URL; resolve-assets freezes it via --from.
const SINGLE_QUERY_IMG = new Set(["photo", "image-reveal", "spotlight", "parallax"]);
const normTitle = (s) => clean(s).toLowerCase();
const imageByTitle = new Map();
const assetManifestArg = opt("--asset-manifest");
if (assetManifestArg) {
  try {
    const mf = JSON.parse(readFileSync(resolve(process.cwd(), assetManifestArg), "utf8"));
    for (const story of mf.stories || []) {
      const img = (story.images || [])[0];
      if (img && img.image_url && story.story_title) {
        imageByTitle.set(normTitle(story.story_title), { url: img.image_url, source: img.source_url || "" });
      }
    }
    if (imageByTitle.size) console.error(`  asset manifest: ${imageByTitle.size} story image(s)`);
  } catch (e) { console.error(`  asset manifest ignored: ${e.message}`); }
}

function ensureRealSourceImage(unitScenes, img) {
  // Present the REAL source image as a browser-frame (the article shown at its URL).
  // browser-frame is intentionally NOT in the LLM menu, so it only ever carries a
  // real source image — never a wrong stock lookup.
  const bf = { query: img.url, url: img.source };
  const existing = unitScenes.find((s) => (SINGLE_QUERY_IMG.has(s.component) || s.component === "browser-frame") && s.params);
  if (existing) { existing.component = "browser-frame"; existing.params = bf; return; }
  if (!unitScenes.length) return;
  // Keep the opening hook scene if we can; convert the longest of the rest (same
  // duration + transition, so audio sync is preserved).
  const pool = unitScenes.length > 1 ? unitScenes.slice(1) : unitScenes;
  const target = pool.reduce((a, b) => ((b.duration || 0) > (a.duration || 0) ? b : a), pool[0]);
  target.component = "browser-frame";
  target.params = bf;
}

// ---------- flatten package into units + beats ----------
const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
const allUnits = Array.isArray(pkg.audio_units) ? pkg.audio_units : [];
const storyCount = allUnits.filter((u) => u.section_type === "story").length;
const audioTotal = (pkg.audio || {}).duration_seconds || 0;

let storyNo = 0;
const units = allUnits.map((u) => {
  const isStory = u.section_type === "story";
  if (isStory) storyNo += 1;
  const beats = (u.aligned_beats || []).map((b) => ({
    beat_id: b.beat_id,
    beat_type: b.beat_type || "",
    beat_function: b.beat_function || "",
    text: clean(b.text),
    emphasis: ((b.delivery_direction || {}).emphasis_phrases || []).map(clean),
    start: Number(b.start_seconds) || 0,
    end: Number(b.end_seconds) || 0,
  }));
  return { id: u.audio_unit_id, section_type: u.section_type, story_title: clean(u.story_title), storyNo: isStory ? storyNo : 0, isStory, beats };
});
// authoritative per-beat duration = gap to next beat start (fill last beat to audio end)
const beatStarts = units.flatMap((u) => u.beats.map((b) => b.start)).sort((a, b) => a - b);
const durOf = (beat) => {
  const nextStart = beatStarts.find((s) => s > beat.start);
  const end = nextStart != null ? nextStart : (audioTotal || beat.end);
  return Math.max(0.8, Number((end - beat.start).toFixed(2)));
};

// ---------- prompt building ----------
function menuText() {
  const lines = Object.entries(menu.components).map(([name, v]) => `- ${name}(${(v.params || []).join(", ")}) — ${v.use}`);
  const rules = (menu.rules || []).map((r) => `- ${r}`).join("\n");
  const tg = (menu.transition_guidance || []).map((r) => `- ${r}`).join("\n");
  return { list: lines.join("\n"), rules, tg };
}
function systemPrompt() {
  const m = menuText();
  return `You are the ART DIRECTOR for a fast, editorial AI-news explainer video.
Theme: clean near-black, one amber + one cyan accent, bold sans + mono labels — a modern, fast tech-explainer look.
You turn each spoken beat into a sequence of on-screen SHOTS using ONLY the component menu.
You do NOT write narration and you do NOT compute timing — you choose components and author concise on-screen copy.

RULES:
${m.rules}

COMPONENT MENU (name(params) — when to use):
${m.list}

TRANSITIONS you may request into a shot: ${[...validTransitions].join(", ")}
${m.tg}

OUTPUT — return ONLY a JSON object, no prose, no markdown fences:
{"shots":[{"beat_id":"<one of the beat ids given>","component":"<menu name>","params":{...only that component's params...},"weight":<1-${cfg.max_shots_per_beat || 3}>,"transition":"<optional, into this shot>"}]}
- Cover EVERY given beat_id at least once, in beat order.
- Split a long beat into up to ${cfg.max_shots_per_beat || 3} shots (a mini establish→develop→payoff); weight = each shot's share of that beat's seconds.
- params keys must EXACTLY match the chosen component; values are SHORT (rewrite, don't paste narration).
- Only use data/diagram components when the beat's own text gives real numbers/steps; never invent values.`;
}
function userPrompt(unit) {
  const head = unit.isStory
    ? `STORY ${unit.storyNo} of ${storyCount}: "${unit.story_title}"`
    : `SECTION: ${unit.section_type}`;
  const beats = unit.beats.map((b) => {
    const secs = durOf(b);
    return `[${b.beat_id}] role=${b.beat_type}/${b.beat_function} seconds=${secs}\n  emphasis: ${b.emphasis.join(" | ") || "(none)"}\n  text: "${b.text}"`;
  }).join("\n\n");
  return `${head}\nAuthor shots for these beats, in order:\n\n${beats}`;
}

// ---------- DeepSeek call ----------
async function callLLM(system, user) {
  const apiKey = loadApiKey();
  const body = { model: cfg.model, messages: [{ role: "system", content: system }, { role: "user", content: user }] };
  const r = cfg.reasoning || {};
  if (r.thinking) body.thinking = { type: r.thinking };
  if (r.reasoning_effort) body.reasoning_effort = r.reasoning_effort;
  if (!r.omit_temperature) body.temperature = 0.7;
  const res = await fetch(`${cfg.base_url.replace(/\/$/, "")}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout((cfg.request_timeout_seconds || 600) * 1000),
  });
  if (!res.ok) throw new Error(`DeepSeek ${res.status}: ${(await res.text()).slice(0, 400)}`);
  const data = await res.json();
  return data.choices?.[0]?.message?.content || "";
}
function extractJson(text) {
  let t = text.replace(/```json\s*|\s*```/g, "").trim();
  const a = t.indexOf("{"), b = t.lastIndexOf("}");
  if (a >= 0 && b > a) t = t.slice(a, b + 1);
  return JSON.parse(t);
}

// ---------- validate + normalize one unit's shots ----------
function scenesForUnit(unit, shots, isFirstUnit) {
  const byBeat = new Map(unit.beats.map((b) => [b.beat_id, []]));
  for (const s of Array.isArray(shots) ? shots : []) {
    if (!byBeat.has(s.beat_id) || !validComponents.has(s.component) || typeof s.params !== "object" || !s.params) continue;
    // keep only known params for the component
    const allowed = componentParams[s.component];
    const params = {};
    for (const k of allowed) {
      if (s.params[k] !== undefined) params[k] = s.params[k];
      else if (BLANKABLE.has(k)) params[k] = ""; // hide, don't fall back to a stale default
    }
    // Overwrite any model-authored channel handle/kicker with the real identity.
    const brand = CHANNEL_PARAM[s.component];
    if (brand && allowed.includes(brand[0])) params[brand[0]] = brand[1];
    const transition = validTransitions.has(s.transition) ? s.transition : undefined;
    byBeat.get(s.beat_id).push({ component: s.component, params, weight: Math.max(1, Number(s.weight) || 1), transition });
  }
  const scenes = [];
  unit.beats.forEach((b, bi) => {
    let list = byBeat.get(b.beat_id);
    if (!list.length) list = [{ component: "kinetic-sentence", params: { text: firstSentence(b.text).slice(0, 120) }, weight: 1 }]; // fallback
    const Dbeat = durOf(b);
    const sumW = list.reduce((a, s) => a + s.weight, 0);
    let used = 0;
    list.forEach((s, si) => {
      let d = si === list.length - 1 ? Number((Dbeat - used).toFixed(2)) : Number((Dbeat * s.weight / sumW).toFixed(2));
      d = Math.max(0.6, d); used += d;
      const scene = { component: s.component, duration: d };
      // transition INTO this scene
      if (!(isFirstUnit && bi === 0 && si === 0)) {
        scene.transition = s.transition || (bi === 0 && si === 0 ? (unit.storyNo === 1 ? "push" : "dip") : "crossfade");
      }
      scene.params = s.params;
      scenes.push(scene);
    });
  });
  return scenes;
}

// ---------- main ----------
const chosen = units.slice(startUnit, startUnit + (unitsLimit === Infinity ? units.length : unitsLimit));
const runTag = (pkg.run_id || basename(dirname(pkgPath))).replace(/[^a-z0-9_]+/gi, "_").slice(0, 40);
const outPath = resolve(process.cwd(), opt("--out") || resolve(projectRoot, `content/${runTag}-ad.yaml`));
const audioOpt = opt("--audio");
const audioRel = relative(projectRoot, audioOpt ? resolve(process.cwd(), audioOpt) : resolve(dirname(pkgPath), "full_voiceover.wav"));

const sys = systemPrompt();
const allScenes = [];
for (let i = 0; i < chosen.length; i++) {
  const unit = chosen[i];
  const usr = userPrompt(unit);
  if (dryRun) { console.log(`\n===== UNIT ${startUnit + i} (${unit.id}) =====\n${usr}`); continue; }
  process.stderr.write(`Planning unit ${startUnit + i + 1}/${chosen.length} (${unit.section_type} ${unit.story_title || ""})… `);
  let shots = null, err = null;
  for (let attempt = 0; attempt < (cfg.max_attempts || 2); attempt++) {
    try { shots = extractJson(await callLLM(sys, usr)).shots; break; }
    catch (e) { err = e; process.stderr.write(`retry(${e.message.slice(0, 80)})… `); }
  }
  if (!shots) { process.stderr.write(`FAILED, using fallback\n`); shots = []; if (err) console.error("  last error:", err.message); }
  else process.stderr.write(`ok (${shots.length} shots)\n`);
  const unitScenes = scenesForUnit(unit, shots, i === 0 && startUnit === 0);
  if (unit.isStory) {
    const img = imageByTitle.get(normTitle(unit.story_title));
    if (img) ensureRealSourceImage(unitScenes, img);
  }
  allScenes.push(...unitScenes);
}

if (dryRun) process.exit(0);

const doc = { audio: audioRel, scenes: allScenes };
const header = `# GENERATED by scripts/art-director/llm.mjs from ${basename(pkgPath)}
# LLM art-director (DeepSeek ${cfg.model}). ${allScenes.length} scenes across ${chosen.length} unit(s).
# Timing is code-enforced from real voiceover; the LLM chose components + copy.
`;
writeFileSync(outPath, header + yaml.dump(doc, { lineWidth: 100 }));
console.log(`Wrote ${relative(projectRoot, outPath)} — ${allScenes.length} scenes, audio=${audioRel}`);
