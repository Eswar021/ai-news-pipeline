import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type RankedItem = {
  rank?: number | string;
  label?: string;
  value?: string;
  detail?: string;
};

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const itemsFromPayload = (value: unknown): RankedItem[] => {
  const items = objectList<Record<string, unknown>>(value)
    .map((item, index) => ({
      rank: item.rank as number | string | undefined,
      label: textValue(item.label) || textValue(item.name),
      value: textValue(item.value),
      detail: textValue(item.detail) || textValue(item.context),
    }))
    .filter((item) => item.label || item.detail || item.value);
  return items.slice(0, 5).map((item, index) => ({ ...item, rank: item.rank || index + 1 }));
};

export const RankedListScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || "What matters most";
  const eyebrow = sceneEyebrow(payload, "RANKED");
  const kicker = textValue(payload.kicker_text) || textValue(payload.emphasis_label);
  const kickerPosition = textValue(payload.kicker_position) || "hidden";
  const showKicker = Boolean(kicker) && (payload.show_kicker === true || kickerPosition !== "hidden");
  const p = spring({ fps, frame, config: { damping: 17, stiffness: 118, mass: 0.72 } });
  const items = itemsFromPayload(payload.items).length
    ? itemsFromPayload(payload.items)
    : [
        { rank: 1, label: "Speed", value: "now", detail: "faster product cycles" },
        { rank: 2, label: "Cost", value: "down", detail: "more teams can deploy" },
        { rank: 3, label: "Control", value: "up", detail: "workflow ownership matters" },
      ];

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "abstract_ai"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.cyan, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 122 : 92, fontSize: readableTitleSize(headline, 84), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>
      {showKicker && kickerPosition !== "bottom" && <div style={{ position: "absolute", right: 96, top: 132, maxWidth: 520, padding: "16px 22px", borderRadius: 999, background: `${palette.amber}18`, border: `1px solid ${palette.amber}55`, color: palette.amber, fontSize: 26, lineHeight: 1, fontWeight: 900, textAlign: "right" }}>{kicker}</div>}

      <div style={{ position: "absolute", left: 138, right: 138, top: 288, display: "grid", gridTemplateRows: `repeat(${items.length}, 1fr)`, gap: 22 }}>
        {items.map((item, index) => {
          const start = 15 + index * 13;
          const reveal = clamp01(interpolate(frame, [start, start + 16], [0, 1], { extrapolateRight: "clamp" }));
          const accent = index === 0 ? palette.amber : index === 1 ? palette.cyan : palette.green;
          return (
            <div key={`${item.label}-${index}`} style={{ opacity: reveal, transform: `translateX(${interpolate(reveal, [0, 1], [56, 0])}px) scale(${interpolate(p, [0, 1], [0.985, 1])})`, display: "grid", gridTemplateColumns: "110px 1fr 240px", gap: 26, alignItems: "center", padding: "23px 28px", borderRadius: 34, background: index === 0 ? "rgba(255,207,112,0.13)" : "rgba(255,255,255,0.078)", border: `1px solid ${index === 0 ? "rgba(255,207,112,0.34)" : "rgba(255,255,255,0.14)"}`, boxShadow: "0 24px 90px rgba(0,0,0,0.26)" }}>
              <div style={{ width: 82, height: 82, borderRadius: 26, display: "flex", alignItems: "center", justifyContent: "center", background: accent, color: "#061016", fontSize: 42, fontWeight: 950, letterSpacing: "-0.06em" }}>{item.rank}</div>
              <div>
                <div style={{ fontSize: 46, lineHeight: 0.95, fontWeight: 940, letterSpacing: "-0.055em" }}>{item.label || `Item ${index + 1}`}</div>
                {item.detail && <div style={{ marginTop: 10, color: "#d5e3f3", fontSize: 26, lineHeight: 1.06, fontWeight: 730 }}>{item.detail}</div>}
              </div>
              {item.value && <div style={{ color: accent, textAlign: "right", fontSize: 50, lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{item.value}</div>}
            </div>
          );
        })}
      </div>

      {showKicker && kickerPosition === "bottom" && <div style={{ position: "absolute", left: 138, bottom: 70, color: palette.amber, fontSize: 31, fontWeight: 900 }}>{kicker}</div>}
    </AbsoluteFill>
  );
};
