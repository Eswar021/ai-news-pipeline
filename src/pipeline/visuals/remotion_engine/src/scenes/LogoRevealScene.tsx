import React from "react";
import { Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import * as icons from "simple-icons";
import { EditorialCanvas } from "./EditorialCanvas";
import { VisualSceneSpec } from "./types";
import { clamp01, editorialStyle, listValue, readableBodySize, readableTitleSize, sceneEyebrow, textValue } from "./style";

export const LogoRevealScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const logo = asset.logo || {};
  const colors = editorialStyle(spec.visual_style);
  const primary = textValue(payload.primary_entity) || textValue(logo.primary_entity);
  const entities = listValue(payload.entities).slice(0, 4);
  const companion = textValue(payload.companion_text) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "IDENTITY");
  const enter = spring({ fps, frame, config: { damping: 18, stiffness: 112, mass: 0.74 } });
  const iconExport = textValue(logo.simple_icon_export);
  const icon = iconExport ? (icons as Record<string, any>)[iconExport] : null;
  const assetDataUri = textValue(asset.asset_data_uri);
  const isTextIdentity = textValue(logo.quality_class) === "text_identity_fallback" || (!icon && !assetDataUri);
  const brandAccent = icon?.hex ? `#${icon.hex}` : colors.accent;
  const visibleEntities = entities.filter((entity) => entity.toLowerCase() !== primary.toLowerCase());

  return (
    <EditorialCanvas spec={spec} accentPosition="right">
      <div style={{ position: "absolute", left: 138, top: 128, bottom: 116, width: 1020, display: "flex", flexDirection: "column", justifyContent: "center" }}>
        {eyebrow && <div style={{ color: colors.accent, fontSize: 25, fontWeight: 850, letterSpacing: "0.19em", textTransform: "uppercase" }}>{eyebrow}</div>}
        <div style={{ marginTop: eyebrow ? 28 : 0, maxWidth: 940, fontFamily: colors.editorialFont, fontSize: readableTitleSize(primary || companion, 112), lineHeight: 0.91, fontWeight: 700, letterSpacing: "-0.052em" }}>{primary || companion}</div>
        {primary && companion && <div style={{ marginTop: 34, maxWidth: 850, color: colors.muted, fontSize: readableBodySize(companion, 38), lineHeight: 1.17, fontWeight: 560 }}>{companion}</div>}
        {visibleEntities.length > 0 && (
          <div style={{ marginTop: 44, display: "flex", alignItems: "center", gap: 18, color: colors.muted, fontSize: 24, fontWeight: 720 }}>
            {visibleEntities.map((entity, index) => (
              <React.Fragment key={entity}>
                {index > 0 && <span style={{ color: colors.accent }}>•</span>}
                <span>{entity}</span>
              </React.Fragment>
            ))}
          </div>
        )}
      </div>

      <div style={{ position: "absolute", right: 132, top: 252, width: 510, height: 470, display: "flex", alignItems: "center", justifyContent: "center", opacity: clamp01(enter), transform: `scale(${interpolate(enter, [0, 1], [0.78, 1])}) translateY(${interpolate(enter, [0, 1], [24, 0])}px)` }}>
        {isTextIdentity ? (
          <div style={{ width: 390, textAlign: "center" }}>
            <div style={{ fontFamily: colors.editorialFont, fontSize: readableTitleSize(primary, 76), lineHeight: 0.94, fontWeight: 700, letterSpacing: "-0.04em" }}>{primary}</div>
            <div style={{ margin: "30px auto 0", width: 250, height: 7, background: colors.accent }} />
          </div>
        ) : icon ? (
          <svg width="300" height="300" viewBox="0 0 24 24" fill={brandAccent} style={{ filter: "drop-shadow(0 16px 28px rgba(45,34,22,0.18))" }}>
            <path d={icon.path} />
          </svg>
        ) : (
          <Img src={assetDataUri} style={{ width: 340, height: 340, objectFit: "contain", filter: "drop-shadow(0 16px 28px rgba(45,34,22,0.18))" }} />
        )}
      </div>
    </EditorialCanvas>
  );
};
