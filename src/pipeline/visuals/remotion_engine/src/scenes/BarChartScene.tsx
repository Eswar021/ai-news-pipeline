import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type BarItem = {
  label?: string;
  value?: number | string;
  display_value?: string;
  context?: string;
};

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const numberValue = (value: unknown, fallback: number) => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  const parsed = Number(String(value ?? "").replace(/[^0-9.-]/g, ""));
  return Number.isFinite(parsed) ? parsed : fallback;
};

const barsFromPayload = (value: unknown): BarItem[] => {
  const items = objectList<Record<string, unknown>>(value)
    .map((item) => ({
      label: textValue(item.label) || textValue(item.name),
      value: item.value as number | string | undefined,
      display_value: textValue(item.display_value) || textValue(item.value),
      context: textValue(item.context) || textValue(item.detail),
    }))
    .filter((item) => item.label || item.display_value);
  return items.slice(0, 5);
};

export const BarChartScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "COMPARISON");
  const bars = barsFromPayload(payload.bars);
  const maxValue = Math.max(...bars.map((bar) => Math.max(1, numberValue(bar.value, 0))), 1);
  const kicker = textValue(payload.kicker_text) || textValue(payload.emphasis_label);
  const kickerPosition = textValue(payload.kicker_position) || "hidden";
  const showKicker = Boolean(kicker) && (payload.show_kicker === true || kickerPosition !== "hidden");
  const unit = textValue(payload.unit);
  const p = spring({ fps, frame, config: { damping: 17, stiffness: 112, mass: 0.72 } });

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "newsroom_grid"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.green, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 122 : 92, fontSize: readableTitleSize(headline, 84), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>
        {headline}
      </div>
      {showKicker && kickerPosition !== "bottom" && <div style={{ position: "absolute", right: 96, top: 132, maxWidth: 520, padding: "16px 22px", borderRadius: 999, background: `${palette.cyan}18`, border: `1px solid ${palette.cyan}55`, color: palette.cyan, fontSize: 26, lineHeight: 1, fontWeight: 900, textAlign: "right" }}>{kicker}</div>}

      <div style={{ position: "absolute", left: 150, right: 150, top: 300, display: "flex", flexDirection: "column", gap: 28 }}>
        {bars.map((bar, index) => {
          const value = Math.max(1, numberValue(bar.value, 0));
          const start = 16 + index * 12;
          const reveal = clamp01(interpolate(frame, [start, start + 28], [0, 1], { extrapolateRight: "clamp" }));
          const width = Math.max(0.08, value / maxValue) * reveal;
          const color = index % 3 === 0 ? palette.cyan : index % 3 === 1 ? palette.amber : palette.green;
          return (
            <div key={`${bar.label}-${index}`} style={{ opacity: reveal, transform: `translateY(${interpolate(reveal, [0, 1], [26, 0])}px) scale(${interpolate(p, [0, 1], [0.985, 1])})` }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 22, marginBottom: 10 }}>
                <div style={{ fontSize: 34, lineHeight: 1, fontWeight: 900, letterSpacing: "-0.035em" }}>{bar.label}</div>
                <div style={{ color, fontSize: 42, lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{bar.display_value || value}{unit && !String(bar.display_value || "").includes(unit) ? <span style={{ color: palette.muted, fontSize: 26, marginLeft: 8 }}>{unit}</span> : null}</div>
              </div>
              <div style={{ position: "relative", height: 56, borderRadius: 999, background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.12)", overflow: "hidden" }}>
                <div style={{ width: `${width * 100}%`, height: "100%", borderRadius: 999, background: `linear-gradient(90deg, ${color}, rgba(255,255,255,0.92))`, boxShadow: `0 0 34px ${color}66` }} />
                {bar.context && <div style={{ position: "absolute", left: 26, top: 14, color: "#071018", fontSize: 23, fontWeight: 850, opacity: width > 0.45 ? 0.88 : 0 }}>{bar.context}</div>}
              </div>
            </div>
          );
        })}
      </div>

      {showKicker && kickerPosition === "bottom" && <div style={{ position: "absolute", left: 150, bottom: 74, padding: "18px 26px", borderRadius: 999, background: `${palette.cyan}1f`, border: `1px solid ${palette.cyan}66`, color: palette.cyan, fontSize: 30, fontWeight: 900 }}>{kicker}</div>}
    </AbsoluteFill>
  );
};
