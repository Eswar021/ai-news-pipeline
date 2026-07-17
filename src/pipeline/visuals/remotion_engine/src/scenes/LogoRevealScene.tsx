import React from "react";
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import * as icons from "simple-icons";
import { MotionBackground } from "./Background";
import { EditorialCanvas } from "./EditorialCanvas";
import { VisualSceneSpec } from "./types";
import { clamp01, editorialStyle, font, isEditorialMinimal, listValue, palette, readableBodySize, readableTitleSize, sceneEyebrow, textValue } from "./style";

export const LogoRevealScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const logo = asset.logo || {};
  const primary = textValue(payload.primary_entity) || textValue(logo.primary_entity);
  const entities = listValue(payload.entities).slice(0, 4);
  const companion = textValue(payload.companion_text) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "ENTITY MOMENT");
  const p = spring({ fps, frame, config: { damping: 16, stiffness: 120, mass: 0.7 } });
  const badgeScale = interpolate(p, [0, 1], [0.72, 1]);
  const iconExport = textValue(logo.simple_icon_export);
  const icon = iconExport ? (icons as Record<string, any>)[iconExport] : null;
  const qualityClass = textValue(logo.quality_class);
  const isTextIdentity = qualityClass === "text_identity_fallback" || (!icon && !asset.asset_data_uri);
  const editorial = isEditorialMinimal(spec.visual_style);
  const editorialColors = editorialStyle(spec.visual_style);
  const brandAccent = icon?.hex ? `#${icon.hex}` : editorial ? editorialColors.accent : palette.cyan;
  const visibleIconFill = "#f7fbff";
  const companionText = companion;
  const headline = isTextIdentity ? companionText || primary : primary;
  const supportingCopy = isTextIdentity ? "" : companionText;
  const visibleEntities = entities.filter(
    (entity) => !isTextIdentity || entity.trim().toLowerCase() !== primary.trim().toLowerCase(),
  );
  if (editorial) {
    return (
      <EditorialCanvas spec={spec} accentPosition="right">
        <div style={{ position: "absolute", left: 140, top: 120, bottom: 110, width: 1000, display: "flex", flexDirection: "column", justifyContent: "center" }}>
          {eyebrow && <div style={{ color: editorialColors.accent, fontSize: 26, fontWeight: 850, letterSpacing: "0.19em", textTransform: "uppercase" }}>{eyebrow}</div>}
          <div style={{ marginTop: eyebrow ? 30 : 0, maxWidth: 940, fontFamily: editorialColors.editorialFont, fontSize: readableTitleSize(headline, isTextIdentity ? 94 : 116), lineHeight: 0.91, fontWeight: 700, letterSpacing: "-0.052em" }}>{headline}</div>
          {supportingCopy && <div style={{ marginTop: 34, maxWidth: 860, color: editorialColors.muted, fontSize: readableBodySize(supportingCopy, 37), lineHeight: 1.18, fontWeight: 560 }}>{supportingCopy}</div>}
          {visibleEntities.length > 0 && (
            <div style={{ marginTop: 42, display: "flex", alignItems: "center", gap: 18, color: editorialColors.muted, fontSize: 25, fontWeight: 750 }}>
              {visibleEntities.map((entity, index) => (
                <React.Fragment key={entity}>
                  {index > 0 && <span style={{ color: editorialColors.accent }}>•</span>}
                  <span>{entity}</span>
                </React.Fragment>
              ))}
            </div>
          )}
        </div>

        <div style={{ position: "absolute", right: 170, top: 270, width: 430, height: 430, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(255,253,248,0.72)", border: `3px solid ${brandAccent}88`, boxShadow: "0 30px 80px rgba(45,34,22,0.16)", opacity: clamp01(p), transform: `scale(${badgeScale}) rotate(${interpolate(p, [0, 1], [-4, 0])}deg)` }}>
          {isTextIdentity ? (
            <div style={{ width: 330, textAlign: "center" }}>
              <div style={{ color: editorialColors.accent, fontSize: 20, fontWeight: 850, letterSpacing: "0.18em", textTransform: "uppercase" }}>Identity</div>
              <div style={{ marginTop: 18, fontFamily: editorialColors.editorialFont, fontSize: readableTitleSize(primary, 64), lineHeight: 0.94, fontWeight: 700, letterSpacing: "-0.04em" }}>{primary}</div>
            </div>
          ) : icon ? (
            <svg width="245" height="245" viewBox="0 0 24 24" fill={brandAccent} style={{ filter: "drop-shadow(0 14px 24px rgba(45,34,22,0.18))" }}>
              <path d={icon.path} />
            </svg>
          ) : asset.asset_data_uri ? (
            <Img src={asset.asset_data_uri} style={{ width: 250, height: 250, objectFit: "contain", filter: "drop-shadow(0 14px 24px rgba(45,34,22,0.18))" }} />
          ) : null}
        </div>
      </EditorialCanvas>
    );
  }

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif="device_glow" />
      {eyebrow && <div style={{ position: "absolute", left: 108, top: 92, color: palette.cyan, fontSize: 28, fontWeight: 900, letterSpacing: "0.2em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 118, top: eyebrow ? 184 : 148, width: 780 }}>
        <div style={{ fontSize: readableTitleSize(headline, isTextIdentity ? 78 : 104), lineHeight: 0.91, fontWeight: 950, letterSpacing: "-0.055em" }}>{headline}</div>
        {supportingCopy && <div style={{ marginTop: 28, color: "#d7e4f1", fontSize: readableBodySize(supportingCopy, 39), lineHeight: 1.1, fontWeight: 760 }}>{supportingCopy}</div>}
      </div>

      <div style={{ position: "absolute", right: 170, top: 214, width: 430, height: 430, borderRadius: 96, display: "flex", alignItems: "center", justifyContent: "center", background: `radial-gradient(circle at 30% 24%, ${brandAccent}42, transparent 42%), linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.045))`, border: `2px solid ${brandAccent}55`, boxShadow: `0 44px 130px rgba(0,0,0,0.50), 0 0 72px ${brandAccent}24`, opacity: clamp01(p), transform: `scale(${badgeScale}) rotate(${interpolate(p, [0, 1], [-5, 0])}deg)` }}>
        <div style={{ position: "absolute", inset: 38, borderRadius: 78, background: "rgba(5,10,16,0.78)", border: "1px solid rgba(255,255,255,0.12)" }} />
        {isTextIdentity ? (
          <div style={{ position: "relative", zIndex: 1, width: 330, textAlign: "center" }}>
            <div style={{ color: palette.cyan, fontSize: 18, fontWeight: 900, letterSpacing: "0.22em", textTransform: "uppercase" }}>Identity</div>
            <div style={{ marginTop: 18, fontSize: readableTitleSize(primary, 66), lineHeight: 0.94, fontWeight: 950, letterSpacing: "-0.045em" }}>{primary}</div>
          </div>
        ) : icon ? (
          <svg width="250" height="250" viewBox="0 0 24 24" fill={visibleIconFill} style={{ position: "relative", filter: `drop-shadow(0 0 22px ${brandAccent}55)` }}>
            <path d={icon.path} />
          </svg>
        ) : asset.asset_data_uri ? (
          <Img src={asset.asset_data_uri} style={{ position: "relative", width: 252, height: 252, objectFit: "contain", filter: "drop-shadow(0 20px 38px rgba(0,0,0,0.48))" }} />
        ) : null}
      </div>

      <div style={{ position: "absolute", left: 118, right: 118, bottom: 94, display: "flex", gap: 18, flexWrap: "wrap" }}>
        {visibleEntities.map((entity, index) => (
          <div key={entity} style={{ opacity: clamp01(interpolate(frame, [28 + index * 8, 44 + index * 8], [0, 1], { extrapolateRight: "clamp" })), color: index === 0 ? "#061016" : palette.text, background: index === 0 ? palette.cyan : "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.16)", borderRadius: 999, padding: "14px 22px", fontSize: 28, fontWeight: 900 }}>
            {entity}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
