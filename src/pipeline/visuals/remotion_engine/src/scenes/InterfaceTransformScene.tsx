import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { EditorialCanvas } from "./EditorialCanvas";
import { VisualSceneSpec } from "./types";
import { clamp01, editorialStyle, listValue, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

type Panel = { title?: string; elements?: string[] };

const panelFromPayload = (value: unknown): Panel => {
  if (typeof value === "string") return { title: value, elements: [] };
  const source = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  return {
    title: textValue(source.title) || textValue(source.label),
    elements: (listValue(source.elements).length ? listValue(source.elements) : listValue(source.items)).slice(0, 4),
  };
};

export const InterfaceTransformScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const colors = editorialStyle(spec.visual_style);
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "WORKFLOW SHIFT");
  const before = panelFromPayload(payload.before);
  const after = panelFromPayload(payload.after);
  const label = textValue(payload.transformation_label);
  const enter = spring({ fps, frame, config: { damping: 19, stiffness: 104, mass: 0.78 } });
  const shift = clamp01(interpolate(frame, [38, 92], [0, 1], { extrapolateRight: "clamp" }));

  const panel = (value: Panel, side: "before" | "after") => {
    const active = side === "after";
    const items = value.elements || [];
    return (
      <div style={{ width: 690, minHeight: 500, padding: "38px 42px", background: active ? "#fffdfa" : "rgba(255,253,250,0.56)", border: `1px solid ${active ? colors.accent : colors.text}35`, boxShadow: active ? "0 28px 80px rgba(45,34,22,0.16)" : "none", opacity: active ? 0.35 + shift * 0.65 : 1 - shift * 0.45 }}>
        <div style={{ color: active ? colors.accent : colors.muted, fontSize: 21, fontWeight: 850, letterSpacing: "0.16em", textTransform: "uppercase" }}>{value.title}</div>
        <div style={{ marginTop: 32, display: "flex", flexDirection: "column", gap: 24 }}>
          {items.map((item, index) => {
            const reveal = clamp01(interpolate(frame, [14 + index * 10 + (active ? 38 : 0), 30 + index * 10 + (active ? 38 : 0)], [0, 1], { extrapolateRight: "clamp" }));
            return (
              <div key={`${item}-${index}`} style={{ display: "grid", gridTemplateColumns: "42px 1fr", gap: 18, alignItems: "center", opacity: reveal }}>
                <div style={{ width: 36, height: 36, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", border: `2px solid ${active ? colors.accent : colors.muted}`, color: active ? colors.accent : colors.muted, fontSize: 18, fontWeight: 820 }}>{index + 1}</div>
                <div style={{ paddingBottom: 16, borderBottom: `1px solid ${colors.text}24`, color: colors.text, fontSize: 30, lineHeight: 1.02, fontWeight: 700 }}>{shortDisplayText(item, 58)}</div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <EditorialCanvas spec={spec} accentPosition="center">
      <div style={{ position: "absolute", left: 98, right: 98, top: 78 }}>
        {eyebrow && <div style={{ color: colors.accent, fontSize: 22, fontWeight: 850, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
        <div style={{ marginTop: eyebrow ? 14 : 0, fontFamily: colors.editorialFont, fontSize: readableTitleSize(headline, 72), lineHeight: 0.94, fontWeight: 700, letterSpacing: "-0.045em" }}>{headline}</div>
      </div>

      <div style={{ position: "absolute", left: 100, right: 100, top: 292, display: "flex", alignItems: "center", justifyContent: "space-between", opacity: clamp01(enter) }}>
        {panel(before, "before")}
        <div style={{ width: 250, display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
          <div style={{ width: 190, height: 4, background: `linear-gradient(90deg, ${colors.muted}55, ${colors.accent})`, transform: `scaleX(${shift})`, transformOrigin: "left" }} />
          <div style={{ color: colors.accent, fontSize: 64, lineHeight: 1 }}>→</div>
          {label && <div style={{ color: colors.muted, fontSize: 22, lineHeight: 1.1, fontWeight: 760, textAlign: "center" }}>{shortDisplayText(label, 48)}</div>}
        </div>
        {panel(after, "after")}
      </div>
    </EditorialCanvas>
  );
};
