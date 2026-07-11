import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, listValue, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type Panel = {
  title?: string;
  elements?: string[];
};

const objectValue = (value: unknown): Record<string, unknown> => (value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {});

const panelFromPayload = (value: unknown, fallbackTitle: string, fallbackItems: string[]): Panel => {
  if (typeof value === "string") {
    return { title: value, elements: fallbackItems };
  }
  const obj = objectValue(value);
  return {
    title: textValue(obj.title) || textValue(obj.label) || fallbackTitle,
    elements: (listValue(obj.elements).length ? listValue(obj.elements) : listValue(obj.points)).slice(0, 4).concat([]).slice(0, 4) || fallbackItems,
  };
};

const defaultElements = (items: string[], fallback: string[]) => (items.length ? items : fallback);

export const InterfaceTransformScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || "The workflow changes shape";
  const eyebrow = sceneEyebrow(payload, "INTERFACE TRANSFORM");
  const beforePanel = panelFromPayload(payload.before, "Before", ["Manual search", "Copy details", "Wait for handoff"]);
  const afterPanel = panelFromPayload(payload.after, "After", ["Ask once", "Agent uses tools", "Work lands in the app"]);
  beforePanel.elements = defaultElements(beforePanel.elements || [], ["Manual search", "Copy details", "Wait for handoff"]);
  afterPanel.elements = defaultElements(afterPanel.elements || [], ["Ask once", "Agent uses tools", "Work lands in the app"]);
  const label = textValue(payload.transformation_label) || "from chat to action";
  const p = spring({ fps, frame, config: { damping: 18, stiffness: 112, mass: 0.72 } });
  const wipe = clamp01(interpolate(frame, [42, 94], [0, 1], { extrapolateRight: "clamp" }));

  const renderPanel = (panel: Panel, color: string, side: "left" | "right") => (
    <div style={{ width: 700, height: 520, borderRadius: 48, padding: "42px 46px", background: side === "left" ? "rgba(255,255,255,0.075)" : `${color}18`, border: `2px solid ${side === "left" ? "rgba(255,255,255,0.16)" : color}`, boxShadow: side === "right" ? `0 40px 140px ${color}25` : "0 34px 110px rgba(0,0,0,0.34)" }}>
      <div style={{ color, fontSize: 28, fontWeight: 950, letterSpacing: "0.14em", textTransform: "uppercase" }}>{panel.title || (side === "left" ? "Before" : "After")}</div>
      <div style={{ marginTop: 34, display: "flex", flexDirection: "column", gap: 18 }}>
        {(panel.elements || []).slice(0, 4).map((item, index) => {
          const reveal = clamp01(interpolate(frame, [18 + index * 9 + (side === "right" ? 46 : 0), 34 + index * 9 + (side === "right" ? 46 : 0)], [0, 1], { extrapolateRight: "clamp" }));
          return (
            <div key={`${item}-${index}`} style={{ opacity: reveal, transform: `translateX(${interpolate(reveal, [0, 1], [side === "left" ? -24 : 24, 0])}px)`, display: "grid", gridTemplateColumns: "54px 1fr", gap: 18, alignItems: "center", padding: "18px 20px", borderRadius: 26, background: "rgba(255,255,255,0.095)", border: "1px solid rgba(255,255,255,0.12)" }}>
              <div style={{ width: 50, height: 50, borderRadius: 18, background: color, color: "#071018", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24, fontWeight: 950 }}>{index + 1}</div>
              <div style={{ color: palette.text, fontSize: 30, lineHeight: 0.98, fontWeight: 850, letterSpacing: "-0.035em" }}>{item}</div>
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "device_glow"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.cyan, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 122 : 92, fontSize: readableTitleSize(headline, 84), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>

      <div style={{ position: "absolute", left: 105, right: 105, top: 318, display: "flex", justifyContent: "space-between", alignItems: "center", opacity: clamp01(p), transform: `translateY(${interpolate(p, [0, 1], [46, 0])}px)` }}>
        {renderPanel(beforePanel, palette.amber, "left")}
        <div style={{ position: "relative", width: 240, height: 160, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ position: "absolute", width: 220, height: 8, borderRadius: 999, background: "rgba(255,255,255,0.16)" }} />
          <div style={{ position: "absolute", left: 10, height: 8, width: `${200 * wipe}px`, borderRadius: 999, background: palette.cyan, boxShadow: `0 0 34px ${palette.cyan}77` }} />
          <div style={{ position: "absolute", right: 16 + (1 - wipe) * 190, color: palette.cyan, fontSize: 72, fontWeight: 950 }}>→</div>
        </div>
        {renderPanel(afterPanel, palette.cyan, "right")}
      </div>

      <div style={{ position: "absolute", left: 540, right: 540, bottom: 82, padding: "20px 26px", borderRadius: 999, textAlign: "center", background: `${palette.cyan}1f`, border: `1px solid ${palette.cyan}66`, color: palette.cyan, fontSize: 34, lineHeight: 1, fontWeight: 930, letterSpacing: "-0.035em" }}>{label}</div>
    </AbsoluteFill>
  );
};
