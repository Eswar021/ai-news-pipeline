# Vendored browser libraries

Committed on purpose so renders never depend on the network **or** on `npm install`.
`scripts/build.mjs` inlines these into the generated `index.html`.

- **gsap.min.js** — GSAP 3.14.2, the animation engine that drives every scene
  timeline. A CDN/network miss at render time loads `null`, `gsap.timeline()`
  throws, and the episode collapses to a static, text-only video — so it is
  committed here rather than fetched at render time.

  To update: `npm i gsap@<version>` in a scratch dir, copy its `dist/gsap.min.js`
  here, bump this note, and re-render one episode to confirm motion.
