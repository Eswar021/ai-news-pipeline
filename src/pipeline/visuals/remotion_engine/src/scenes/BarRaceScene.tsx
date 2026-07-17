import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type RaceItem = {
  label?: string;
  start_value?: number | string;
  end_value?: number | string;
  display_value?: string;
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

const itemsFromPayload = (value: unknown): RaceItem[] => {
  const items = objectList<Record<string, unknown>>(value)
    .map((item) => ({
      label: textValue(item.label) || textValue(item.name),
      start_value: item.start_value as number | string | undefined,
      end_value: item.end_value as number | string | undefined,
      display_value: textValue(item.display_value) || textValue(item.end_value) || textValue(item.value),
    }))
    .filter((item) => item.label || item.display_value);
  return items.slice(0, 5);
};

export const BarRaceScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "RACE VIEW");
  const unit = textValue(payload.unit);
  const kicker = textValue(payload.kicker_text) || textValue(payload.leader_label);
  const kickerPosition = textValue(payload.kicker_position) || "hidden";
  const showKicker = Boolean(kicker) && (payload.show_kicker === true || kickerPosition !== "hidden");
  const progress = clamp01(interpolate(frame, [16, Math.max(18, durationInFrames - 18)], [0, 1], { extrapolateRight: "clamp" }));
  const items = itemsFromPayload(payload.items);
  const liveItems = items
    .map((item, index) => {
      const start = numberValue(item.start_value, 0);
      const end = numberValue(item.end_value, 0);
      const value = start + (end - start) * progress;
      return { ...item, value, color: index % 3 === 0 ? palette.cyan : index % 3 === 1 ? palette.amber : palette.green };
    })
    .sort((a, b) => b.value - a.value);
  const maxValue = Math.max(...liveItems.map((item) => item.value), 1);

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "device_glow"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.amber, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 122 : 92, fontSize: readableTitleSize(headline, 84), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>
      {showKicker && kickerPosition !== "bottom" && <div style={{ position: "absolute", right: 96, top: 132, maxWidth: 520, padding: "16px 22px", borderRadius: 999, background: `${palette.cyan}18`, border: `1px solid ${palette.cyan}55`, color: palette.cyan, fontSize: 26, lineHeight: 1, fontWeight: 900, textAlign: "right" }}>{kicker}</div>}

      <div style={{ position: "absolute", left: 150, right: 150, top: 306, display: "flex", flexDirection: "column", gap: 26 }}>
        {liveItems.map((item, index) => {
          const width = Math.max(0.08, item.value / maxValue);
          return (
            <div key={`${item.label}-${index}`} style={{ transform: `translateY(${interpolate(progress, [0, 1], [10, 0])}px)`, transition: "none" }}>
              <div style={{ display: "grid", gridTemplateColumns: "270px 1fr 150px", gap: 24, alignItems: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  <div style={{ width: 56, height: 56, borderRadius: 18, display: "flex", alignItems: "center", justifyContent: "center", background: item.color, color: "#061016", fontSize: 26, fontWeight: 950 }}>{index + 1}</div>
                  <div style={{ fontSize: 33, lineHeight: 0.98, fontWeight: 900, letterSpacing: "-0.04em" }}>{item.label}</div>
                </div>
                <div style={{ height: 62, borderRadius: 999, background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.12)", overflow: "hidden" }}>
                  <div style={{ width: `${width * 100}%`, height: "100%", borderRadius: 999, background: `linear-gradient(90deg, ${item.color}, rgba(255,255,255,0.92))`, boxShadow: `0 0 38px ${item.color}66` }} />
                </div>
                <div style={{ color: item.color, textAlign: "right", fontSize: 42, lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>
                  {item.display_value || Math.round(item.value)}{unit && <span style={{ color: palette.muted, fontSize: 24, marginLeft: 6 }}>{unit}</span>}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {showKicker && kickerPosition === "bottom" && <div style={{ position: "absolute", left: 150, bottom: 74, color: palette.cyan, fontSize: 31, lineHeight: 1, fontWeight: 900 }}>{kicker}</div>}
    </AbsoluteFill>
  );
};
