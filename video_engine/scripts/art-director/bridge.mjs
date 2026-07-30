// Deterministic art-director bridge (v1).
//
//   node scripts/art-director/bridge.mjs <voiceover_package.json> [options]
//
// Reads a voiceover_package.json from the upstream content+voiceover pipeline and
// emits one of OUR scene YAML files (consumed by scripts/build.mjs). It maps each
// aligned beat -> a scene using scripts/art-director/beat-map.yaml, sets scene
// durations from AUTHORITATIVE voiceover timing, chooses transitions from beat
// structure, and attaches the full narration WAV as the master audio track.
//
// It IGNORES upstream visual_goal/visual_brief on purpose — visual decisions are
// ours. It reads only: beat_type, beat_function, narration text, emphasis
// phrases, story identity, and per-beat timing.
//
// Options:
//   --out <path>          output YAML (default: content/<run>-bridge.yaml)
//   --audio <path>        master WAV path, relative to the video_engine root
//   --max-seconds <n>     dev slice: stop after this much narration time
//
// This is a PROOF-OF-CHAIN pass. The LLM art-director will supersede the mapping
// (better component/copy choices; splitting long beats into shot sequences).

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve, relative, basename } from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "js-yaml";

const here = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(here, "..", "..");

// ---- args ----
const args = process.argv.slice(2);
const pkgArg = args.find((a) => !a.startsWith("--"));
const getOpt = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};
if (!pkgArg) {
  console.error("usage: node scripts/art-director/bridge.mjs <voiceover_package.json> [--out ..] [--audio ..] [--max-seconds n]");
  process.exit(1);
}
const pkgPath = resolve(process.cwd(), pkgArg);
const maxSeconds = getOpt("--max-seconds") ? Number(getOpt("--max-seconds")) : Infinity;

const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
const map = yaml.load(readFileSync(resolve(here, "beat-map.yaml"), "utf8")) || {};
const beatMap = map.beats || {};
const fnMap = map.functions || {};
const D = map.defaults || {};

// audio path: default to the WAV sitting next to the package, made relative to root.
const audioOpt = getOpt("--audio");
const audioAbs = audioOpt
  ? resolve(process.cwd(), audioOpt)
  : resolve(dirname(pkgPath), "full_voiceover.wav");
const audioRel = relative(projectRoot, audioAbs);

const runTag = (pkg.run_id || basename(dirname(pkgPath))).replace(/[^a-z0-9_]+/gi, "_").slice(0, 40);
const outPath = resolve(process.cwd(), getOpt("--out") || resolve(projectRoot, `content/${runTag}-bridge.yaml`));

// ---- text helpers (deterministic) ----
const clean = (s) => String(s || "").replace(/\s+/g, " ").trim();
const firstSentence = (t) => {
  const parts = clean(t).split(/(?<=[.!?])\s+/);
  return parts[0] || clean(t);
};
const truncate = (t, n) => {
  if (t.length <= n) return t;
  const cut = t.slice(0, n);
  const sp = cut.lastIndexOf(" ");
  return (sp > n * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s—,:;]+$/, "") + "…";
};
const secondSentence = (t) => {
  const parts = clean(t).split(/(?<=[.!?])\s+/);
  return parts[1] ? clean(parts[1]) : " "; // a space blanks a component's default slot
};
const NUM_RE = /(\$?\d[\d,\.]*\s?(?:billion|million|thousand|percent|%|square feet|jobs|panels|books|tons?|dollars)?)/i;
const findNumber = (beat) => {
  const emph = (beat.delivery_direction || {}).emphasis_phrases || [];
  for (const p of emph) {
    const m = String(p).match(NUM_RE);
    if (m && /\d/.test(m[1])) return clean(m[1]);
  }
  const m = clean(beat.text).match(NUM_RE);
  return m && /\d/.test(m[1]) ? clean(m[1]) : "";
};
// wrap emphasis phrases found in a text with *..* for kinetic-sentence emphasis.
const withEmphasis = (text, beat) => {
  let out = text;
  const emph = ((beat.delivery_direction || {}).emphasis_phrases || []).slice(0, 2);
  for (const p of emph) {
    const clp = clean(p).replace(/[—,]+$/, "");
    if (clp && out.includes(clp)) { out = out.replace(clp, `*${clp}*`); break; }
  }
  return out;
};

// ---- flatten beats, tracking story numbering ----
const units = Array.isArray(pkg.audio_units) ? pkg.audio_units : [];
const storyUnits = units.filter((u) => u.section_type === "story");
const totalStories = storyUnits.length;
const audioTotal = (pkg.audio || {}).duration_seconds || 0;

const flat = [];
let storyNo = 0;
units.forEach((u) => {
  const isStory = u.section_type === "story";
  if (isStory) storyNo += 1;
  (u.aligned_beats || []).forEach((b, bi) => {
    flat.push({ beat: b, unit: u, isStory, storyNo, firstOfUnit: bi === 0 });
  });
});

// ---- component recipes (deterministic param authoring) ----
function recipe(component, ctx) {
  const { beat, unit, storyNo } = ctx;
  const text = clean(beat.text);
  const storyTitle = clean(unit.story_title);
  switch (component) {
    case "title-card":
      return { kicker: storyTitle ? truncate(storyTitle, 40) : "AI NEWS", title: truncate(firstSentence(text), 90), subtitle: secondSentence(text) };
    case "section-marker":
      return { index: storyNo, total: totalStories, label: truncate(storyTitle || firstSentence(text), 40), sublabel: " " };
    case "stat-punch": {
      const value = findNumber(beat);
      if (!value) return null; // trigger fallback
      return { eyebrow: truncate(storyTitle || "BY THE NUMBERS", 40), value, caption: truncate(firstSentence(text), 60) };
    }
    case "quote-card":
      return { quote: truncate(firstSentence(text), 160), author: storyTitle ? "" : "", role: "" };
    case "kinetic-sentence":
    default:
      return { text: truncate(withEmphasis(firstSentence(text), beat), 120) };
  }
}

function chooseComponent(beat) {
  const fn = fnMap[beat.beat_function];
  if (fn && fn.component) return fn;
  return beatMap[beat.beat_type] || { component: "kinetic-sentence" };
}

// ---- build scenes ----
const scenes = [];
let prevUnitId = null;
for (let i = 0; i < flat.length; i++) {
  const ctx = flat[i];
  const b = ctx.beat;
  const start = Number(b.start_seconds) || 0;
  if (start >= maxSeconds) break;
  const next = flat[i + 1];
  const rawEnd = next ? Number(next.beat.start_seconds) : (audioTotal || Number(b.end_seconds));
  const end = Math.min(rawEnd, maxSeconds);
  const duration = Math.max(0.8, Number((end - start).toFixed(2)));

  const rule = chooseComponent(b);
  let component = rule.component;
  let params = recipe(component, ctx);
  if (params === null && rule.fallback) { component = rule.fallback; params = recipe(component, ctx); }
  if (params === null) { component = "kinetic-sentence"; params = recipe(component, ctx); }

  // transition INTO this scene
  let transition;
  if (i === 0) transition = undefined; // opening fade is automatic
  else if (ctx.isStory && ctx.firstOfUnit) transition = ctx.storyNo === 1 ? D.first_story_transition : D.story_transition;
  else if (ctx.unit.audio_unit_id !== prevUnitId) transition = D.story_transition;
  else transition = D.transition;

  const scene = { component, duration };
  if (transition) scene.transition = transition;
  scene.params = params;
  scenes.push(scene);
  prevUnitId = ctx.unit.audio_unit_id;
}

const doc = { audio: audioRel, scenes };
const header = `# GENERATED by scripts/art-director/bridge.mjs from ${basename(pkgPath)}
# Deterministic v1 bridge — beats mapped via beat-map.yaml, timing from real voiceover.
# Edit the bridge/beat-map, not this file. ${scenes.length} scenes.
`;
writeFileSync(outPath, header + yaml.dump(doc, { lineWidth: 100 }));
console.log(`Bridge: ${flat.length} beats -> ${scenes.length} scenes (${maxSeconds === Infinity ? audioTotal : maxSeconds}s), audio=${audioRel}`);
console.log(`Wrote ${relative(projectRoot, outPath)}`);
