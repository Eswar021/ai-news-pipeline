import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import * as icons from "simple-icons";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, listValue, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

const iconForEntity = (entity: string) => {
  const normalized = entity.toLowerCase().replace(/[^a-z0-9]/g, "");
  const key = Object.keys(icons).find((item) => item.toLowerCase().replace(/^si/, "") === normalized);
  return key ? (icons as Record<string, any>)[key] : null;
};

export const EntityCompareScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || "The players are shifting";
  const axis = textValue(payload.comparison_axis);
  const entities = listValue(payload.entities).slice(0, 4);
  const notes = listValue(payload.entity_notes);
  const eyebrow = sceneEyebrow(payload, "ENTITY MAP");
  const p = spring({ fps, frame, config: { damping: 17, stiffness: 110, mass: 0.74 } });

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif="device_glow" />
      {eyebrow && (
        <div style={{ position: "absolute", left: 94, top: 74, color: palette.cyan, fontSize: 24, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>
      )}
      <div style={{ position: "absolute", left: 96, top: eyebrow ? 126 : 96, right: 96, fontSize: readableTitleSize(headline, 82), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>
        {headline}
      </div>
      {axis && <div style={{ position: "absolute", left: 100, top: 236, color: palette.amber, fontSize: 35, fontWeight: 850 }}>{axis}</div>}

      <div style={{ position: "absolute", left: 96, right: 96, top: axis ? 328 : 302, display: "grid", gridTemplateColumns: `repeat(${Math.max(2, Math.min(4, entities.length || 2))}, 1fr)`, gap: 28 }}>
        {(entities.length ? entities : ["AI", "Platform"]).map((entity, index) => {
          const icon = iconForEntity(entity);
          const start = 20 + index * 14;
          const opacity = clamp01(interpolate(frame, [start, start + 14], [0, 1], { extrapolateRight: "clamp" }));
          const y = interpolate(opacity, [0, 1], [52, 0]);
          return (
            <div key={`${entity}-${index}`} style={{ opacity, transform: `translateY(${y}px) scale(${interpolate(p, [0, 1], [0.98, 1])})`, minHeight: 360, borderRadius: 36, padding: "34px 30px", background: "rgba(255,255,255,0.078)", border: "1px solid rgba(255,255,255,0.15)", boxShadow: "0 34px 110px rgba(0,0,0,0.32)" }}>
              <div style={{ width: 128, height: 128, borderRadius: 38, display: "flex", alignItems: "center", justifyContent: "center", background: index % 2 === 0 ? `${palette.cyan}22` : `${palette.amber}22`, border: "1px solid rgba(255,255,255,0.18)" }}>
                {icon ? (
                  <svg width="78" height="78" viewBox="0 0 24 24" fill={`#${icon.hex || "f7fbff"}`}>
                    <path d={icon.path} />
                  </svg>
                ) : (
                  <div style={{ fontSize: 54, fontWeight: 950 }}>{entity.slice(0, 2).toUpperCase()}</div>
                )}
              </div>
              <div style={{ marginTop: 28, fontSize: 42, lineHeight: 0.96, fontWeight: 950, letterSpacing: "-0.05em" }}>{entity}</div>
              <div style={{ marginTop: 18, color: "#cbd8e8", fontSize: 25, lineHeight: 1.14, fontWeight: 720 }}>{notes[index] || "Strategic pressure is rising"}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
