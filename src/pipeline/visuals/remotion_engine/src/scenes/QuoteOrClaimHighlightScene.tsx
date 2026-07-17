import React from "react";
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

export const QuoteOrClaimHighlightScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const headline = textValue(payload.overlay_headline) || spec.scene.script_excerpt || "";
  const claim = textValue(payload.claim_text) || spec.scene.script_excerpt || "";
  const supporting = textValue(payload.supporting_text);
  const eyebrow = sceneEyebrow(payload, "SOURCE CLAIM");
  const claimLabel = textValue(payload.claim_label);
  const image = asset.asset_data_uri || "";
  const p = spring({ fps, frame, config: { damping: 19, stiffness: 112, mass: 0.72 } });
  const imageScale = interpolate(frame, [0, durationInFrames], [1.04, 1.12]);
  const cardY = interpolate(p, [0, 1], [72, 0]);
  const scan = interpolate(frame, [20, durationInFrames - 16], [-240, 1180], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif="newsroom_grid" />
      {eyebrow && <div style={{ position: "absolute", left: 78, top: 58, color: palette.cyan, fontSize: 24, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 78, top: eyebrow ? 108 : 72, right: 78, fontSize: readableTitleSize(headline, 62), lineHeight: 0.94, fontWeight: 950, letterSpacing: "-0.05em" }}>
        {headline}
      </div>

      <div style={{ position: "absolute", left: 72, top: 244, width: 1040, bottom: 80, borderRadius: 34, overflow: "hidden", border: "1px solid rgba(255,255,255,0.18)", background: palette.panelStrong, boxShadow: "0 40px 120px rgba(0,0,0,0.46)" }}>
        {image ? (
          <Img src={image} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${imageScale})`, transformOrigin: "center center", opacity: 0.9 }} />
        ) : (
          <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: palette.muted, fontSize: 42, fontWeight: 900 }}>SOURCE SCREENSHOT UNAVAILABLE</div>
        )}
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(7,11,16,0.08), rgba(7,11,16,0.62))" }} />
        <div style={{ position: "absolute", top: 0, bottom: 0, left: scan, width: 180, background: "linear-gradient(90deg, transparent, rgba(255,207,112,0.24), transparent)", filter: "blur(3px)" }} />
      </div>

      <div style={{ position: "absolute", right: 90, top: 306, width: 690, padding: "46px 48px", borderRadius: 38, background: "rgba(8,15,25,0.92)", border: `2px solid ${palette.amber}88`, boxShadow: "0 42px 140px rgba(0,0,0,0.56)", opacity: clamp01(p), transform: `translateY(${cardY}px)` }}>
        {claimLabel && <div style={{ color: palette.amber, fontSize: 25, fontWeight: 950, letterSpacing: "0.15em", textTransform: "uppercase" }}>{claimLabel}</div>}
        <div style={{ marginTop: claimLabel ? 24 : 0, fontSize: readableTitleSize(claim, 60), lineHeight: 0.94, fontWeight: 950, letterSpacing: "-0.055em" }}>
          {claim}
        </div>
        {supporting && (
          <div style={{ marginTop: 30, color: "#d7e4f1", fontSize: 27, lineHeight: 1.15, fontWeight: 760 }}>
            {supporting}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
