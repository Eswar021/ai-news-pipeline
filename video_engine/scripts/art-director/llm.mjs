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

// Format-awareness: a deep-dive is ONE topic explained across sequential angle
// segments, so a numbered "story N of M" divider is nonsense — section-marker is
// roundup-only (roundup also gets one deterministically per story, below). Deleting
// it here removes it from both the shown menu and the accepted set.
const FORMAT = (opt("--format") || "").toLowerCase();
const isDeepDive = FORMAT === "deep_dive";
if (isDeepDive) validComponents.delete("section-marker");
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

// ---------- research facts (optional; deep-dive only) ----------
// The dossier's SHOWABLE structured facts (timeline, numbers, quotes, sources) so the
// art-director can build real timeline / stat / quote / montage visuals FROM THE RESEARCH
// — not only from what the narration happens to restate. Grounded: use ONLY these, never
// invent. Absent (roundup, or a run without research) → planning is unchanged.
let researchPack = null;
const researchArg = opt("--research");
if (researchArg) {
  try {
    researchPack = JSON.parse(readFileSync(resolve(process.cwd(), researchArg), "utf8"));
    const c = (k) => (researchPack[k] || []).length;
    console.error(`  research pack: ${c("timeline")} timeline, ${c("numbers")} numbers, ${c("quotes")} quotes, ${c("sources")} sources`);
  } catch (e) { console.error(`  research pack ignored: ${e.message}`); }
}
function researchFactsBlock() {
  if (!researchPack) return "";
  const parts = [];
  const tl = (researchPack.timeline || []).filter((e) => e && e.event);
  if (tl.length) parts.push("TIMELINE — when ANY beat recounts how things unfolded (a sequence, dates, 'over N days', 'first… then…'), you MUST render it as a `timeline` from these events (events:[{date,label}], label ≤4 words), never as plain text:\n" + tl.map((e) => `  - ${e.date || "—"} — ${e.event}`).join("\n"));
  const nums = (researchPack.numbers || []).filter((n) => n && n.value);
  if (nums.length) parts.push("NUMBERS (each → a `stat-punch`: value + short caption):\n" + nums.map((n) => `  - ${n.value} — ${n.context || ""}`).join("\n"));
  const qs = (researchPack.quotes || []).filter((q) => q && q.text);
  if (qs.length) parts.push("QUOTES (each → a `quote-from-source`: quote/meta/source):\n" + qs.map((q) => `  - "${q.text}" — ${q.speaker || "?"}${q.source ? ` (${q.source})` : ""}`).join("\n"));
  const src = (researchPack.sources || []).filter((s) => s && s.title);
  if (src.length) parts.push("SOURCES (build ONE `multi-source-montage`, sources:[{source,headline}]):\n" + src.map((s) => `  - ${s.source || "?"}: ${s.title}`).join("\n"));
  if (!parts.length) return "";
  return `\nRESEARCH FACTS — real, independently sourced. Reach for these to build grounded timeline / stat-punch / quote-from-source / multi-source-montage shots WHERE ONE FITS A BEAT, even if the narration doesn't restate the exact number. Use ONLY these facts; never invent values, dates, or quotes.\n\n${parts.join("\n\n")}\n`;
}

const EPISODE_OPEN_MAX = 5; // the intro bumper must hit fast — never a long frozen open
function capEpisodeOpen(scenes) {
  // The opening bumper used to hold ~12s on one card (the #1 retention killer). Cap it
  // and continue the hook as a moving line so the first seconds keep moving.
  const first = scenes[0];
  if (!first || first.component !== "episode-open" || (first.duration || 0) <= EPISODE_OPEN_MAX + 1.5) return;
  const p = first.params || {};
  const cont = clean(p.subtitle || p.title || "").slice(0, 90);
  const rest = Number(((first.duration || 0) - EPISODE_OPEN_MAX).toFixed(2));
  first.duration = EPISODE_OPEN_MAX;
  if (cont) scenes.splice(1, 0, { component: "kinetic-sentence", duration: rest, transition: "crossfade", params: { text: cont } });
  else first.duration = Number((first.duration + rest).toFixed(2)); // nothing to cut to — leave it
}

// Deep-dive deterministic polish (only when a research pack is present). The prompt asks
// for these; this is the floor when the LLM doesn't comply. Content-safe — it only ever
// touches fallback text cards and duplicate stats, never a purposeful visual.
function applyResearchPolish(scenes) {
  if (!researchPack || scenes.length < 3) return;
  // 1. Guarantee the chronology shows as a timeline: if the LLM placed none, upgrade the
  //    longest FILLER text card (never the opening hook or closing scene) to the timeline.
  const events = (researchPack.timeline || []).filter((e) => e && e.event);
  if (events.length >= 4 && !scenes.some((s) => s.component === "timeline")) {
    const target = scenes.slice(1, -1)
      .filter((s) => s.component === "kinetic-sentence" || s.component === "title-card")
      .sort((a, b) => (b.duration || 0) - (a.duration || 0))[0];
    if (target) {
      target.component = "timeline";
      target.params = { title: "How it unfolded", events: events.slice(0, 6).map((e) => ({ date: clean(e.date).slice(0, 24), label: shortLabel(e.event, 4) })) };
    }
  }
  // 2. Never repeat a stat value across the episode — swap a duplicate for an unused
  //    research number (keeps the punchy stat-punch, adds a distinct fact).
  const norm = (v) => clean(v).toLowerCase().replace(/[^a-z0-9.%]/g, "");
  const seen = new Set();
  for (const s of scenes) {
    if (s.component !== "stat-punch" || !s.params || !s.params.value) continue;
    const key = norm(s.params.value);
    if (!seen.has(key)) { seen.add(key); continue; }
    const alt = (researchPack.numbers || []).find((n) => n && n.value && !seen.has(norm(n.value)));
    if (alt) { s.params = { eyebrow: s.params.eyebrow || "", value: alt.value, caption: shortLabel(alt.context, 6) }; seen.add(norm(alt.value)); }
  }
}

const BROWSER_FRAME_MAX = 7; // a STATIC source screenshot must not hold longer than this
const DIVIDER_SECONDS = 2.8; // fixed length of an injected numbered story divider

function ensureRealSourceImage(unitScenes, img) {
  // Present the REAL source image as a browser-frame (the article shown at its URL).
  // browser-frame is intentionally NOT in the LLM menu, so it only ever carries a
  // real source image — never a wrong stock lookup.
  const bf = { query: img.url, url: img.source };
  if (!unitScenes.length) return;
  // Prefer converting an existing single-image scene; else the longest after the hook.
  let idx = unitScenes.findIndex((s) => (SINGLE_QUERY_IMG.has(s.component) || s.component === "browser-frame") && s.params);
  if (idx < 0) {
    const pool = unitScenes.length > 1 ? unitScenes.slice(1) : unitScenes;
    const target = pool.reduce((a, b) => ((b.duration || 0) > (a.duration || 0) ? b : a), pool[0]);
    idx = unitScenes.indexOf(target);
  }
  const target = unitScenes[idx];
  const original = { component: target.component, params: target.params };
  target.component = "browser-frame";
  target.params = bf;
  // Cap the static hold: show the real image for BROWSER_FRAME_MAX, then cut back to the
  // scene's original visual for the remainder (keeps the unit's audio sync exact). This
  // is why real images used to freeze for 15-22s — the inject took the LONGEST scene.
  if ((target.duration || 0) > BROWSER_FRAME_MAX + 1.5 && original.component !== "browser-frame") {
    const rest = Number(((target.duration || 0) - BROWSER_FRAME_MAX).toFixed(2));
    target.duration = BROWSER_FRAME_MAX;
    unitScenes.splice(idx + 1, 0, { component: original.component, duration: rest, transition: "crossfade", params: original.params });
  }
}

const TRAIL_STOP = new Set(["to", "and", "of", "the", "by", "a", "an", "in", "on", "for", "with", "at", "as", "or", "from", "its", "their", "into"]);
function shortLabel(title, maxWords = 5) {
  const words = clean(title).split(" ").slice(0, maxWords);
  // Don't let a truncated label dangle on a function word ("… detects and").
  while (words.length > 1 && TRAIL_STOP.has(words[words.length - 1].toLowerCase())) words.pop();
  const out = words.join(" ");
  return out.length > 40 ? out.slice(0, 38).trimEnd() + "…" : out;
}

function ensureStoryDivider(unitScenes, unit, total) {
  // ROUNDUP only: GUARANTEE each story opens with a numbered "N of M" divider instead of
  // leaving it to per-unit LLM whim (which fired for only 1 of 5 stories last run).
  if (!unitScenes.length) return;
  const num = { index: unit.storyNo, total };
  const existingIdx = unitScenes.findIndex((s) => s.component === "section-marker");
  if (existingIdx >= 0) {
    // The LLM already made one — keep its authored label, fix the numbering, open with it.
    const sm = unitScenes[existingIdx];
    sm.params = { ...sm.params, ...num };
    if (existingIdx > 0) { unitScenes.splice(existingIdx, 1); unitScenes.unshift(sm); }
    return;
  }
  const params = { ...num, label: shortLabel(unit.story_title), sublabel: "" };
  const first = unitScenes[0];
  if ((first.duration || 0) > DIVIDER_SECONDS + 1.2) {
    // Prepend a short divider, taking its time from the first scene so the unit's total
    // duration (audio sync) is unchanged; it inherits the story-entry transition.
    unitScenes.unshift({ component: "section-marker", duration: DIVIDER_SECONDS, transition: first.transition || "dip", params });
    first.duration = Number(((first.duration || 0) - DIVIDER_SECONDS).toFixed(2));
    first.transition = "crossfade";
  } else {
    first.component = "section-marker";
    first.params = params;
  }
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
  const lines = Object.entries(menu.components).filter(([name]) => validComponents.has(name)).map(([name, v]) => `- ${name}(${(v.params || []).join(", ")}) — ${v.use}`);
  const rules = (menu.rules || []).map((r) => `- ${r}`).join("\n");
  const tg = (menu.transition_guidance || []).map((r) => `- ${r}`).join("\n");
  return { list: lines.join("\n"), rules, tg };
}
function systemPrompt() {
  const m = menuText();
  const formatNote = isDeepDive
    ? "FORMAT: single-topic DEEP-DIVE — the whole video explains ONE story in depth across sequential angle segments. Never number segments ('N of M') and never use a story divider; move between segments with chapter-like transitions (dip / push). Lean HARD on diagrams, sequences, timelines, and data to explain the mechanism — plain text cards are a last resort here."
    : "FORMAT: multi-story ROUNDUP — several distinct stories in sequence. OPEN each new story with a section-marker as its FIRST shot, giving it a punchy 2-4 word label (the '1 of N' numbering is added for you — you just supply a great label). Then tell the story with visual shots.";
  return `You are the ART DIRECTOR for a fast, editorial AI-news explainer video.
Theme: clean near-black, one amber + one cyan accent, bold sans + mono labels — a modern, fast tech-explainer look.
You turn each spoken beat into a sequence of on-screen SHOTS using ONLY the component menu.
You do NOT write narration and you do NOT compute timing — you choose components and author concise on-screen copy.

${formatNote}

RULES:
${m.rules}

COMPONENT MENU (name(params) — when to use):
${m.list}

TRANSITIONS you may request into a shot: ${[...validTransitions].join(", ")}
${m.tg}
${isDeepDive ? researchFactsBlock() : ""}
OUTPUT — return ONLY a JSON object, no prose, no markdown fences:
{"shots":[{"beat_id":"<one of the beat ids given>","component":"<menu name>","params":{...only that component's params...},"weight":<1-${cfg.max_shots_per_beat || 3}>,"transition":"<optional, into this shot>"}]}
- Cover EVERY given beat_id at least once, in beat order.
- Split a long beat into up to ${cfg.max_shots_per_beat || 3} shots (a mini establish→develop→payoff); weight = each shot's share of that beat's seconds.
- params keys must EXACTLY match the chosen component; values are SHORT (rewrite, don't paste narration).
- Only use data/diagram components when the beat's own text gives real numbers/steps; never invent values.`;
}
function userPrompt(unit) {
  const head = !unit.isStory
    ? `SECTION: ${unit.section_type}`
    : isDeepDive
      ? `DEEP-DIVE SEGMENT ${unit.storyNo}: one angle of the single topic "${unit.story_title}". This is ONE continuous explainer — do NOT open with a story divider or number this segment.`
      : `STORY ${unit.storyNo} of ${storyCount}: "${unit.story_title}"`;
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
if (dryRun) console.log(`\n===== SYSTEM PROMPT (format=${FORMAT || "default"}) =====\n${sys}`);
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
    // Roundup: guarantee the numbered story divider. Deep-dive: one topic, no dividers.
    if (!isDeepDive) ensureStoryDivider(unitScenes, unit, storyCount);
  }
  allScenes.push(...unitScenes);
}

capEpisodeOpen(allScenes);      // retention: the intro bumper hits fast, never a 12s freeze
applyResearchPolish(allScenes); // deep-dive floor: guarantee the timeline, de-dup stats

if (dryRun) process.exit(0);

const doc = { audio: audioRel, scenes: allScenes };
const header = `# GENERATED by scripts/art-director/llm.mjs from ${basename(pkgPath)}
# LLM art-director (DeepSeek ${cfg.model}). ${allScenes.length} scenes across ${chosen.length} unit(s).
# Timing is code-enforced from real voiceover; the LLM chose components + copy.
`;
writeFileSync(outPath, header + yaml.dump(doc, { lineWidth: 100 }));
console.log(`Wrote ${relative(projectRoot, outPath)} — ${allScenes.length} scenes, audio=${audioRel}`);
