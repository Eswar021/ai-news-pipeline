import React from "react";
import { Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { EditorialCanvas } from "./EditorialCanvas";
import { VisualSceneSpec } from "./types";
import { clamp01, editorialStyle, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

export const QuoteOrClaimHighlightScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const colors = editorialStyle(spec.visual_style);
  const headline = textValue(payload.overlay_headline) || spec.scene.script_excerpt || "";
  const claim = shortDisplayText(textValue(payload.claim_text) || spec.scene.script_excerpt || "", 96);
  const supporting = shortDisplayText(textValue(payload.supporting_text), 170);
  const eyebrow = sceneEyebrow(payload, "SOURCE PROOF");
  const image = asset.asset_data_uri || "";
  const enter = spring({ fps, frame, config: { damping: 20, stiffness: 105, mass: 0.78 } });
  const scan = interpolate(frame, [18, Math.max(40, durationInFrames - 12)], [-260, 1540], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <EditorialCanvas spec={spec} accentPosition="left">
      <div style={{ position: "absolute", left: 92, right: 92, top: 58, display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 40 }}>
        <div style={{ maxWidth: 1320 }}>
          {eyebrow && <div style={{ color: colors.accent, fontSize: 22, fontWeight: 850, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
          <div style={{ marginTop: eyebrow ? 10 : 0, fontFamily: colors.editorialFont, fontSize: readableTitleSize(headline, 58), lineHeight: 0.95, fontWeight: 700, letterSpacing: "-0.04em" }}>{headline}</div>
        </div>
        <div style={{ color: colors.muted, fontSize: 20, fontWeight: 760 }}>VERIFIED SOURCE</div>
      </div>

      <div style={{ position: "absolute", left: 88, right: 88, top: 205, bottom: 84, overflow: "hidden", background: "#fffdfa", border: `1px solid ${colors.text}2b`, boxShadow: "0 26px 70px rgba(45,34,22,0.15)", opacity: clamp01(enter), transform: `translateY(${interpolate(enter, [0, 1], [28, 0])}px)` }}>
        {image ? (
          <Img src={image} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${interpolate(frame, [0, durationInFrames], [1.02, 1.09])})` }} />
        ) : (
          <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: colors.muted, fontSize: 34, fontWeight: 760 }}>Source capture unavailable</div>
        )}
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, transparent 42%, rgba(244,239,230,0.2) 58%, rgba(244,239,230,0.98) 76%)" }} />
        <div style={{ position: "absolute", left: scan, top: 0, bottom: 0, width: 150, background: `linear-gradient(90deg, transparent, ${colors.accent}28, transparent)` }} />
      </div>

      <div style={{ position: "absolute", right: 118, top: 350, width: 650, paddingLeft: 34, borderLeft: `9px solid ${colors.accent}`, opacity: clamp01(enter), transform: `translateX(${interpolate(enter, [0, 1], [40, 0])}px)` }}>
        <div style={{ fontFamily: colors.editorialFont, fontSize: readableTitleSize(claim, 64), lineHeight: 0.94, fontWeight: 700, letterSpacing: "-0.045em" }}>{claim}</div>
        {supporting && <div style={{ marginTop: 24, color: colors.muted, fontSize: 27, lineHeight: 1.18, fontWeight: 560 }}>{supporting}</div>}
      </div>
    </EditorialCanvas>
  );
};
