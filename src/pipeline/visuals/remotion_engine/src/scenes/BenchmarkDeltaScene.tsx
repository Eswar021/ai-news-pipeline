import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableBodySize, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

type BenchmarkItem = {
  label?: string;
  before?: string;
  after?: string;
  delta?: string;
  unit?: string;
  context?: string;
};

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const benchmarksFromPayload = (value: unknown): BenchmarkItem[] => {
  const items = objectList<Record<string, unknown>>(value)
    .map((item) => ({
      label: textValue(item.label) || textValue(item.name),
      before: textValue(item.before),
      after: textValue(item.after),
      delta: textValue(item.delta),
      unit: textValue(item.unit),
      context: textValue(item.context) || textValue(item.detail),
    }))
    .filter((item) => item.label || item.delta || item.before || item.after);
  return items.slice(0, 3);
};

export const BenchmarkDeltaScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || "The benchmark moved";
  const eyebrow = sceneEyebrow(payload, "DELTA");
  const kicker = textValue(payload.kicker_text) || textValue(payload.winner_label);
  const kickerPosition = textValue(payload.kicker_position) || "hidden";
  const showKicker = Boolean(kicker) && (payload.show_kicker === true || kickerPosition !== "hidden");
  const p = spring({ fps, frame, config: { damping: 16, stiffness: 112, mass: 0.72 } });
  const benchmarks = benchmarksFromPayload(payload.benchmarks).length
    ? benchmarksFromPayload(payload.benchmarks)
    : [
        { label: "Latency", before: "1.0x", after: "2.0x", delta: "+100%", context: "faster response" },
        { label: "Cost", before: "$1.00", after: "$0.60", delta: "-40%", context: "lower run cost" },
      ];
  const isHero = benchmarks.length === 1;

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "device_glow"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.green, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 122 : 92, fontSize: readableTitleSize(headline, 84), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>
      {showKicker && kickerPosition !== "bottom" && <div style={{ position: "absolute", right: 96, top: 132, maxWidth: 520, padding: "16px 22px", borderRadius: 999, background: `${palette.green}18`, border: `1px solid ${palette.green}55`, color: palette.green, fontSize: 26, lineHeight: 1, fontWeight: 900, textAlign: "right" }}>{kicker}</div>}

      <div style={{ position: "absolute", left: 116, right: 116, top: isHero ? 282 : 306, display: "grid", gridTemplateColumns: `repeat(${benchmarks.length}, 1fr)`, gap: 28 }}>
        {benchmarks.map((item, index) => {
          const start = 15 + index * 13;
          const reveal = clamp01(interpolate(frame, [start, start + 18], [0, 1], { extrapolateRight: "clamp" }));
          const accent = item.delta?.trim().startsWith("-") ? palette.green : index % 2 === 0 ? palette.cyan : palette.amber;
          const context = shortDisplayText(item.context || "", isHero ? 124 : 86);
          return (
            <div key={`${item.label}-${index}`} style={{ opacity: reveal, transform: `translateY(${interpolate(reveal, [0, 1], [46, 0])}px) scale(${interpolate(p, [0, 1], [0.98, 1])})`, minHeight: isHero ? 520 : 420, borderRadius: 42, padding: isHero ? "46px 54px 44px" : "36px 36px 32px", background: "rgba(255,255,255,0.088)", border: "1px solid rgba(255,255,255,0.16)", boxShadow: "0 34px 110px rgba(0,0,0,0.34)" }}>
              <div style={{ color: accent, fontSize: isHero ? 37 : 30, fontWeight: 920, letterSpacing: "0.08em", textTransform: "uppercase" }}>{shortDisplayText(item.label || "Metric", isHero ? 32 : 22)}</div>
              <div style={{ marginTop: isHero ? 44 : 34, display: "grid", gridTemplateColumns: "1fr auto 1fr", alignItems: "center", gap: isHero ? 30 : 18 }}>
                <div style={{ color: palette.muted, fontSize: isHero ? 64 : 44, lineHeight: 0.9, fontWeight: 900, letterSpacing: "-0.055em" }}>{shortDisplayText(item.before || "before", isHero ? 24 : 16)}</div>
                <div style={{ color: accent, fontSize: isHero ? 60 : 44, fontWeight: 950 }}>→</div>
                <div style={{ color: palette.text, fontSize: isHero ? 76 : 52, lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.065em" }}>{shortDisplayText(item.after || "after", isHero ? 24 : 16)}</div>
              </div>
              <div style={{ marginTop: isHero ? 46 : 34, color: accent, fontSize: readableTitleSize(item.delta || "shift", isHero ? 124 : 86), lineHeight: 0.82, fontWeight: 950, letterSpacing: "-0.09em", textShadow: `0 0 34px ${accent}44` }}>{shortDisplayText(item.delta || "shift", isHero ? 32 : 20)}</div>
              {context && <div style={{ marginTop: isHero ? 34 : 24, color: "#d5e3f3", fontSize: readableBodySize(context, isHero ? 40 : 31), lineHeight: 1.12, fontWeight: 780, maxWidth: isHero ? 1320 : undefined }}>{context}</div>}
            </div>
          );
        })}
      </div>

      {showKicker && kickerPosition === "bottom" && <div style={{ position: "absolute", left: 116, bottom: 74, padding: "18px 28px", borderRadius: 999, background: `${palette.green}1f`, border: `1px solid ${palette.green}66`, color: palette.green, fontSize: 31, fontWeight: 900 }}>{kicker}</div>}
    </AbsoluteFill>
  );
};
