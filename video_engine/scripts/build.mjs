// Runner: reads a YAML params file + the component registry, generates index.html.
//
//   node scripts/build.mjs [content/typography-demo.yaml]
//
// Content YAML (LLM-facing later): scenes = which component(s) + params + how it enters.
//   A scene is either a single component:      { component, duration, params }
//   or a stack of layers composited together:  { duration, layers: [ {component, params}, ... ] }
//   In a layers[] beat, layer 0 is the bottom (track base), each next layer sits on
//   top (base+1, +2, ...) — e.g. a `gradient-bg` under a transparent `lower-third`.
//
//   TRANSITIONS (Glue family G): a scene may declare how it ENTERS from the
//   previous scene via `transition`:
//       transition: push                       # shorthand (uses default duration/dir)
//       transition: { type: whip, dir: left, duration: 0.28 }
//   Types: crossfade (default) · dip · push · whip · zoom · cut (hard cut).
//   The runner overlaps the two scenes and animates the outgoing slot OUT +
//   the incoming slot IN on the MAIN timeline (the transition IS the handoff —
//   see hyperframes-animation/transitions). Each scene gets a rising track base
//   so the incoming scene composites ON TOP of the outgoing one during overlap.
//
// registry.yaml (system config): per component, its family folder + fixed SFX;
// plus a `transitions:` map (type -> whoosh cue). SFX become <audio> at the HOST
// ROOT (HyperFrames requires audio at the root).

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "js-yaml";

const here = dirname(fileURLToPath(import.meta.url));

// GSAP drives every scene timeline. Reference the committed vendor copy with a
// LOCAL relative <script src> so the render server serves it offline (no CDN — a
// CDN miss loads null, gsap.timeline() throws, and the episode falls back to a
// static, text-only video) and the linter skips it (inlining the minified lib
// tripped the non-determinism check on GSAP's own Date.now/Math.random). The path
// is relative to the generated index.html at the project root; CDN is last resort.
const gsapTag = (() => {
  for (const rel of ["vendor/gsap.min.js", "node_modules/gsap/dist/gsap.min.js"]) {
    if (existsSync(resolve(here, "..", rel))) return `<script src="${rel}"></script>`;
  }
  return `<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>`;
})();
const projectRoot = resolve(here, "..");
const contentArg = process.argv[2] || "content/typography-demo.yaml";

const W = 1920;
const H = 1080;
const SCENE_TRACK_STRIDE = 10; // each scene's tracks: i*10+1 .. (room for <10 layers/scene)
const AUDIO_TRACK_BASE = 100000; // keep audio tracks far above any visual track
const OPEN_FADE = 0.5; // fade-from-black on the first scene
const CLOSE_FADE = 0.5; // fade-to-black on the last scene (final-scene exit is allowed)

const doc = yaml.load(readFileSync(resolve(projectRoot, contentArg), "utf8")) || {};
const reg = yaml.load(readFileSync(resolve(projectRoot, "content/registry.yaml"), "utf8")) || {};
const scenes = Array.isArray(doc.scenes) ? doc.scenes : [];
const components = reg.components || {};
const sfxFiles = reg.sfx || {};
const transitionSfx = reg.transitions || {};

if (scenes.length === 0) {
  console.error(`No scenes found in ${contentArg}`);
  process.exit(1);
}

const escAttr = (s) => s.replace(/&/g, "&amp;").replace(/'/g, "&#39;");

function resolveRepeat(rep, params) {
  if (typeof rep === "number") return Math.max(1, rep);
  if (rep === "segments") return Math.max(1, parseInt(params.total, 10) || 1);
  // Generic: repeat named after any array param (items, series, points, …).
  const val = params[rep];
  if (Array.isArray(val)) return Math.max(1, val.length);
  if (typeof val === "string" && val.trim()) return Math.max(1, val.split("|").filter((s) => s.trim()).length);
  return 1;
}

// --- Transition catalog -----------------------------------------------------
// Each returns GSAP tween lines animating the outgoing slot (`out`) OUT and the
// incoming slot (`inc`) IN, both starting at time T over duration td. The motion
// IS the handoff: no separate exit animation, both move at the same T.
const TRANSITION_DEFAULT_DUR = { crossfade: 0.4, dip: 0.5, push: 0.45, whip: 0.28, zoom: 0.5, mask: 0.6, match: 0.5 };

function transitionTweens(type, dir, out, inc, T, td) {
  const t = T.toFixed(3), d = td.toFixed(3);
  const lines = [];
  switch (type) {
    case "dip": {
      // Outgoing fades to the black root in the first half, incoming rises in the second.
      const half = (td / 2).toFixed(3);
      const mid = (T + td / 2).toFixed(3);
      lines.push(`tl.fromTo("${out}", { opacity: 1 }, { opacity: 0, duration: ${half}, ease: "power2.in" }, ${t});`);
      lines.push(`tl.fromTo("${inc}", { opacity: 0 }, { opacity: 1, duration: ${half}, ease: "power2.out" }, ${mid});`);
      break;
    }
    case "push": {
      const sign = dir === "right" || dir === "down" ? 1 : -1;
      const axis = dir === "up" || dir === "down" ? "yPercent" : "xPercent";
      lines.push(`tl.fromTo("${out}", { ${axis}: 0 }, { ${axis}: ${-100 * sign}, duration: ${d}, ease: "power3.inOut" }, ${t});`);
      lines.push(`tl.fromTo("${inc}", { ${axis}: ${100 * sign} }, { ${axis}: 0, duration: ${d}, ease: "power3.inOut" }, ${t});`);
      break;
    }
    case "whip": {
      const sign = dir === "right" ? 1 : -1;
      lines.push(`tl.fromTo("${out}", { xPercent: 0, filter: "blur(0px)" }, { xPercent: ${-100 * sign}, filter: "blur(14px)", duration: ${d}, ease: "power2.in" }, ${t});`);
      lines.push(`tl.fromTo("${inc}", { xPercent: ${100 * sign}, filter: "blur(14px)" }, { xPercent: 0, filter: "blur(0px)", duration: ${d}, ease: "power2.out" }, ${t});`);
      break;
    }
    case "zoom": {
      lines.push(`tl.fromTo("${out}", { scale: 1, opacity: 1 }, { scale: 1.35, opacity: 0, duration: ${d}, ease: "power2.in", transformOrigin: "50% 50%" }, ${t});`);
      lines.push(`tl.fromTo("${inc}", { scale: 0.86, opacity: 0 }, { scale: 1, opacity: 1, duration: ${d}, ease: "power2.out", transformOrigin: "50% 50%" }, ${t});`);
      break;
    }
    case "mask": {
      // circle iris: the incoming scene reveals through an expanding circle (on top of the outgoing)
      lines.push(`tl.fromTo("${inc}", { clipPath: "circle(0% at 50% 50%)" }, { clipPath: "circle(75% at 50% 50%)", duration: ${d}, ease: "power2.inOut" }, ${t});`);
      break;
    }
    case "match": {
      // match cut: outgoing pulls back, incoming settles from slightly larger (a matched zoom blend)
      lines.push(`tl.fromTo("${out}", { scale: 1, opacity: 1 }, { scale: 0.85, opacity: 0, duration: ${d}, ease: "power2.in", transformOrigin: "50% 50%" }, ${t});`);
      lines.push(`tl.fromTo("${inc}", { scale: 1.2, opacity: 0 }, { scale: 1, opacity: 1, duration: ${d}, ease: "power2.out", transformOrigin: "50% 50%" }, ${t});`);
      break;
    }
    case "crossfade":
    default: {
      lines.push(`tl.fromTo("${out}", { opacity: 1 }, { opacity: 0, duration: ${d}, ease: "power1.inOut" }, ${t});`);
      lines.push(`tl.fromTo("${inc}", { opacity: 0 }, { opacity: 1, duration: ${d}, ease: "power1.inOut" }, ${t});`);
      break;
    }
  }
  return lines;
}

// Normalize a scene's `transition` (string | object | undefined) into {type,dir,duration}.
// Scene 0 has no incoming transition; scenes 1+ default to a crossfade.
function normTransition(raw) {
  if (raw === "cut" || (raw && raw.type === "cut")) return null;
  const o = typeof raw === "string" ? { type: raw } : raw || {};
  const type = o.type || "crossfade";
  const dir = o.dir || "left";
  const duration = Number(o.duration) || TRANSITION_DEFAULT_DUR[type] || 0.4;
  return { type, dir, duration };
}

// --- Pass 1: lay out scene windows on the hard-cut grid, then apply overlaps.
const layout = scenes.map((sc, i) => {
  const trans = i === 0 ? null : normTransition(sc.transition);
  return { dur: Number(sc.duration) || 4, trans };
});
let cursor = 0;
layout.forEach((L) => {
  L.start = cursor;
  cursor += L.dur;
});
const total = cursor;
// A scene lingers into the next scene's opening by that next transition's duration,
// so both are alive during the handoff.
layout.forEach((L, i) => {
  const nextTrans = layout[i + 1] && layout[i + 1].trans;
  L.slotDur = L.dur + (nextTrans ? nextTrans.duration : 0);
});

// --- Pass 2: emit slots, SFX, and transition tweens.
let audioIdx = 0;
const slotParts = [];
const audioParts = [];
const tweenLines = [];

const addAudio = (file, st, vol) => {
  audioParts.push(`      <audio id="sfx-${audioIdx}" src="${file}" data-start="${st}" data-track-index="${AUDIO_TRACK_BASE + audioIdx}" data-volume="${vol}"></audio>`);
  audioIdx++;
};

scenes.forEach((sc, i) => {
  const L = layout[i];
  const start = L.start;
  const sceneBase = i * SCENE_TRACK_STRIDE + 1;

  const layers = Array.isArray(sc.layers)
    ? sc.layers
    : [{ component: sc.component, params: sc.params }];

  layers.forEach((ly, li) => {
    const comp = ly.component;
    const entry = components[comp] || {};
    const family = entry.family || "typography";
    const params = ly.params || {};
    const values = escAttr(JSON.stringify(params));
    const track = sceneBase + li;
    // All layers of a scene linger together so the whole scene hands off as one unit.
    const slotDur = L.slotDur;

    slotParts.push(`      <div id="el-${i}-${li}" class="sc-${i}" data-composition-id="${comp}-${i}-${li}"
           data-composition-src="compositions/${family}/${comp}.html"
           data-variable-values='${values}'
           data-start="${start}" data-duration="${slotDur}" data-track-index="${track}"
           data-width="${W}" data-height="${H}"></div>`);

    const cues = Array.isArray(entry.sfx) ? entry.sfx : [];
    cues.forEach((cue) => {
      const file = sfxFiles[cue.cue];
      if (!file) return;
      const vol = cue.volume != null ? cue.volume : 0.5;
      const at = Number(cue.at) || 0;
      const rep = cue.repeat != null ? resolveRepeat(cue.repeat, params) : 1;
      const spread = Number(cue.spread) || 0;
      for (let k = 0; k < rep; k++) {
        addAudio(file, (start + at + k * spread).toFixed(3), vol);
      }
    });
  });

  // Incoming transition for this scene (handoff from scene i-1) — moves the whole scene.
  if (L.trans) {
    tweenLines.push(...transitionTweens(L.trans.type, L.trans.dir, `.sc-${i - 1}`, `.sc-${i}`, start, L.trans.duration));
    const tsfx = transitionSfx[L.trans.type];
    if (tsfx && sfxFiles[tsfx.cue]) addAudio(sfxFiles[tsfx.cue], start.toFixed(3), tsfx.volume != null ? tsfx.volume : 0.3);
  }
});

// Opening fade-from-black and closing fade-to-black (final-scene exit is allowed).
tweenLines.unshift(`tl.fromTo(".sc-0", { opacity: 0 }, { opacity: 1, duration: ${OPEN_FADE.toFixed(3)}, ease: "power1.out" }, 0);`);
const lastStart = layout[scenes.length - 1].start;
const lastDur = layout[scenes.length - 1].dur;
tweenLines.push(`tl.fromTo(".sc-${scenes.length - 1}", { opacity: 1 }, { opacity: 0, duration: ${CLOSE_FADE.toFixed(3)}, ease: "power1.in" }, ${(lastStart + lastDur - CLOSE_FADE).toFixed(3)});`);

// Optional master narration track (top-level `audio:` in the content YAML) —
// the full voiceover WAV, laid at t=0 so scenes stay synced to real beat timing.
if (doc.audio) {
  const mvol = doc.audioVolume != null ? doc.audioVolume : 1;
  audioParts.unshift(`      <audio id="master-vo" src="${doc.audio}" data-start="0" data-track-index="${AUDIO_TRACK_BASE - 1}" data-volume="${mvol}"></audio>`);
}

const slots = slotParts.join("\n\n");
const audio = audioParts.join("\n");
const tweens = tweenLines.map((l) => "      " + l).join("\n");

const html = `<!doctype html>
<html lang="en" data-resolution="landscape">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    ${gsapTag}
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { margin: 0; width: 1920px; height: 1080px; overflow: hidden; background: #06090e; }
      #root { position: relative; width: 1920px; height: 1080px; overflow: hidden; }
      #root > div[data-composition-src] { position: absolute; inset: 0; will-change: transform, opacity, filter; }
    </style>
  </head>
  <body>
    <!-- GENERATED by scripts/build.mjs from ${contentArg} + registry.yaml. Edit those, not this file. -->
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="${total}"
      data-width="${W}"
      data-height="${H}"
    >
${slots}

      <!-- SFX: host-root audio, placed by the runner from registry.yaml -->
${audio}
    </div>

    <script>
      window.__timelines = window.__timelines || {};
      var tl = gsap.timeline({ paused: true });
      // Scene transitions + open/close fades (drive the host slots on the main timeline).
${tweens}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
`;

writeFileSync(resolve(projectRoot, "index.html"), html);
console.log(`Built index.html from ${contentArg} — ${scenes.length} scenes, ${slotParts.length} slots, ${audioIdx} SFX cues, ${tweenLines.length} transition tweens, ${total}s total`);
