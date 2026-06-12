import React from "react";
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import * as icons from "simple-icons";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette } from "./style";

const textValue = (value: unknown) => (typeof value === "string" ? value : "");
const listValue = (value: unknown) => (Array.isArray(value) ? value.map(String).filter(Boolean) : []);

export const LogoRevealScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const logo = asset.logo || {};
  const primary = textValue(payload.primary_entity) || textValue(logo.primary_entity) || "AI";
  const entities = listValue(payload.entities).slice(0, 4);
  const companion = textValue(payload.companion_text) || spec.scene.script_excerpt || "";
  const p = spring({ fps, frame, config: { damping: 16, stiffness: 120, mass: 0.7 } });
  const badgeScale = interpolate(p, [0, 1], [0.72, 1]);
  const iconExport = textValue(logo.simple_icon_export);
  const icon = iconExport ? (icons as Record<string, any>)[iconExport] : null;

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif="device_glow" />
      <div style={{ position: "absolute", left: 108, top: 92, color: palette.cyan, fontSize: 28, fontWeight: 900, letterSpacing: "0.22em" }}>ENTITY MOMENT</div>
      <div style={{ position: "absolute", left: 118, top: 184, width: 730 }}>
        <div style={{ fontSize: 94, lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{primary}</div>
        <div style={{ marginTop: 28, color: "#d7e4f1", fontSize: 39, lineHeight: 1.1, fontWeight: 760 }}>{companion}</div>
      </div>

      <div style={{ position: "absolute", right: 170, top: 214, width: 410, height: 410, borderRadius: 92, display: "flex", alignItems: "center", justifyContent: "center", background: "linear-gradient(135deg, rgba(255,255,255,0.13), rgba(255,255,255,0.035))", border: "1px solid rgba(255,255,255,0.2)", boxShadow: "0 40px 120px rgba(0,0,0,0.48)", opacity: clamp01(p), transform: `scale(${badgeScale}) rotate(${interpolate(p, [0, 1], [-5, 0])}deg)` }}>
        {icon ? (
          <svg width="235" height="235" viewBox="0 0 24 24" fill={`#${icon.hex || "f7fbff"}`}>
            <path d={icon.path} />
          </svg>
        ) : asset.asset_data_uri ? (
          <Img src={asset.asset_data_uri} style={{ width: 238, height: 238, objectFit: "contain" }} />
        ) : (
          <div style={{ fontSize: 124, fontWeight: 950 }}>{primary.slice(0, 2).toUpperCase()}</div>
        )}
      </div>

      <div style={{ position: "absolute", left: 118, right: 118, bottom: 94, display: "flex", gap: 18, flexWrap: "wrap" }}>
        {entities.map((entity, index) => (
          <div key={entity} style={{ opacity: clamp01(interpolate(frame, [28 + index * 8, 44 + index * 8], [0, 1], { extrapolateRight: "clamp" })), color: index === 0 ? "#061016" : palette.text, background: index === 0 ? palette.cyan : "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.16)", borderRadius: 999, padding: "14px 22px", fontSize: 28, fontWeight: 900 }}>
            {entity}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

