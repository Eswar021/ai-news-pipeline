import React from "react";
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import * as icons from "simple-icons";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, listValue, palette, readableBodySize, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

export const LogoRevealScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const logo = asset.logo || {};
  const primary = textValue(payload.primary_entity) || textValue(logo.primary_entity) || "AI";
  const entities = listValue(payload.entities).slice(0, 4);
  const companion = textValue(payload.companion_text) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "ENTITY MOMENT");
  const p = spring({ fps, frame, config: { damping: 16, stiffness: 120, mass: 0.7 } });
  const badgeScale = interpolate(p, [0, 1], [0.72, 1]);
  const iconExport = textValue(logo.simple_icon_export);
  const icon = iconExport ? (icons as Record<string, any>)[iconExport] : null;
  const brandAccent = icon?.hex ? `#${icon.hex}` : palette.cyan;
  const visibleIconFill = "#f7fbff";
  const companionText = shortDisplayText(companion, 116);

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif="device_glow" />
      {eyebrow && <div style={{ position: "absolute", left: 108, top: 92, color: palette.cyan, fontSize: 28, fontWeight: 900, letterSpacing: "0.2em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 118, top: eyebrow ? 184 : 148, width: 780 }}>
        <div style={{ fontSize: readableTitleSize(primary, 104), lineHeight: 0.88, fontWeight: 950, letterSpacing: "-0.065em" }}>{primary}</div>
        <div style={{ marginTop: 28, color: "#d7e4f1", fontSize: readableBodySize(companionText, 39), lineHeight: 1.1, fontWeight: 760 }}>{companionText}</div>
      </div>

      <div style={{ position: "absolute", right: 170, top: 214, width: 430, height: 430, borderRadius: 96, display: "flex", alignItems: "center", justifyContent: "center", background: `radial-gradient(circle at 30% 24%, ${brandAccent}42, transparent 42%), linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.045))`, border: `2px solid ${brandAccent}55`, boxShadow: `0 44px 130px rgba(0,0,0,0.50), 0 0 72px ${brandAccent}24`, opacity: clamp01(p), transform: `scale(${badgeScale}) rotate(${interpolate(p, [0, 1], [-5, 0])}deg)` }}>
        <div style={{ position: "absolute", inset: 38, borderRadius: 78, background: "rgba(5,10,16,0.78)", border: "1px solid rgba(255,255,255,0.12)" }} />
        {icon ? (
          <svg width="250" height="250" viewBox="0 0 24 24" fill={visibleIconFill} style={{ position: "relative", filter: `drop-shadow(0 0 22px ${brandAccent}55)` }}>
            <path d={icon.path} />
          </svg>
        ) : asset.asset_data_uri ? (
          <Img src={asset.asset_data_uri} style={{ position: "relative", width: 252, height: 252, objectFit: "contain", filter: "drop-shadow(0 20px 38px rgba(0,0,0,0.48))" }} />
        ) : (
          <div style={{ position: "relative", fontSize: 124, fontWeight: 950 }}>{primary.slice(0, 2).toUpperCase()}</div>
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
