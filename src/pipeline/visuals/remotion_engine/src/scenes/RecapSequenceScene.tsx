import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { beatList, clamp01, font, listValue, palette, readableBodySize, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

const recapItemsFromText = (text: string) => {
  const trimmed = text.trim();
  if (trimmed.length < 96) {
    return [trimmed];
  }
  const focusText = trimmed.includes(":") ? trimmed.split(":").slice(1).join(":") : trimmed;
  const clauses = focusText
    .split(/[,;]|(?:\sand\s)/gi)
    .map((item) => item.replace(/^(and|but|or)\s+/i, "").trim())
    .filter((item) => item.length >= 18)
    .slice(0, 4);
  if (clauses.length >= 2) {
    return clauses;
  }
  return [trimmed];
};

export const RecapSequenceScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const beats = beatList(payload.beats);
  const explicitItems = listValue(payload.recap_items);
  const beatItems = beats.map((beat) => beat.text || "").filter(Boolean);
  const sourceItems = explicitItems.length ? explicitItems : beatItems;
  const rawItems = sourceItems.length === 1 ? recapItemsFromText(sourceItems[0] || "") : sourceItems;
  const items = rawItems.map((item) => shortDisplayText(item, rawItems.length === 1 ? 122 : 64)).slice(0, 6);
  const takeaway = textValue(payload.final_takeaway);
  const motif = textValue(payload.background_motif) || "abstract_ai";
  const eyebrow = sceneEyebrow(payload, "ROUNDUP RECAP");
  const p = spring({ fps, frame, config: { damping: 18, stiffness: 116, mass: 0.74 } });
  const singleItem = items.length === 1;

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={motif} />
      {eyebrow && (
        <div style={{ position: "absolute", left: 96, top: 72, color: palette.amber, fontSize: 24, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>
      )}
      <div style={{ position: "absolute", left: 96, top: eyebrow ? 126 : 96, right: 96, fontSize: readableTitleSize(headline, 84), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>
        {headline}
      </div>

      <div style={{ position: "absolute", left: singleItem ? 210 : 124, right: singleItem ? 210 : 124, top: singleItem ? 360 : 292, display: "grid", gridTemplateColumns: singleItem ? "1fr" : "1fr 1fr", gap: "24px 30px" }}>
        {items.map((item, index) => {
          const beatStartSeconds = beats[index]?.relative_start_seconds;
          const start = typeof beatStartSeconds === "number" ? Math.max(8, Math.round(beatStartSeconds * fps)) : 16 + index * 16;
          const opacity = clamp01(interpolate(frame, [start, start + 12], [0, 1], { extrapolateRight: "clamp" }));
          const x = interpolate(opacity, [0, 1], [46, 0]);
          return (
            <div key={`${item}-${index}`} style={{ opacity, transform: `translateX(${x}px)`, display: "flex", gap: singleItem ? 28 : 20, alignItems: "center", padding: singleItem ? "36px 44px" : "22px 26px", borderRadius: singleItem ? 38 : 30, background: "rgba(255,255,255,0.078)", border: "1px solid rgba(255,255,255,0.13)", boxShadow: singleItem ? "0 34px 100px rgba(0,0,0,0.30)" : undefined }}>
              <div style={{ width: singleItem ? 72 : 52, height: singleItem ? 72 : 52, borderRadius: 999, background: index % 2 === 0 ? palette.cyan : palette.amber, color: "#061016", display: "flex", alignItems: "center", justifyContent: "center", fontSize: singleItem ? 32 : 24, fontWeight: 950, flexShrink: 0 }}>
                {index + 1}
              </div>
              <div style={{ fontSize: readableBodySize(item, singleItem ? 52 : 34), lineHeight: singleItem ? 1.02 : 1.04, fontWeight: 860, letterSpacing: "-0.035em" }}>{item}</div>
            </div>
          );
        })}
      </div>

      {takeaway && (
        <div style={{ position: "absolute", left: 124, right: 124, bottom: 82, padding: "30px 38px", borderRadius: 34, background: `linear-gradient(90deg, ${palette.cyan}28, ${palette.amber}18)`, border: "1px solid rgba(255,255,255,0.18)", opacity: clamp01(interpolate(frame, [durationInFrames * 0.58, durationInFrames * 0.72], [0, 1], { extrapolateRight: "clamp" })), transform: `scale(${interpolate(p, [0, 1], [0.985, 1])})` }}>
          {textValue(payload.takeaway_label) && <div style={{ color: palette.cyan, fontSize: 22, fontWeight: 950, letterSpacing: "0.16em", textTransform: "uppercase" }}>{textValue(payload.takeaway_label)}</div>}
          <div style={{ marginTop: textValue(payload.takeaway_label) ? 12 : 0, fontSize: 48, lineHeight: 1, fontWeight: 910, letterSpacing: "-0.045em" }}>{takeaway}</div>
        </div>
      )}
    </AbsoluteFill>
  );
};
