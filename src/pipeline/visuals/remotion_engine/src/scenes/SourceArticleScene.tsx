import React from "react";
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, editorialStyle, font, isEditorialMinimal, palette, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

export const SourceArticleScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const p = spring({ fps, frame, config: { damping: 20, stiffness: 110, mass: 0.7 } });
  const continuationCount = Math.max(1, Number(payload.continuation_count || 1));
  const continuationIndex = Math.min(
    continuationCount,
    Math.max(1, Number(payload.continuation_index || 1)),
  );
  const phaseStart = (continuationIndex - 1) / continuationCount;
  const phaseEnd = continuationIndex / continuationCount;
  const imageScale = interpolate(
    frame,
    [0, durationInFrames],
    [1.02 + phaseStart * 0.11, 1.02 + phaseEnd * 0.11],
  );
  const scanX = interpolate(frame, [25, durationInFrames - 18], [-360, 1360], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const headline = textValue(payload.overlay_headline) || spec.scene.script_excerpt || "";
  const targetText = textValue(payload.target_text);
  const targetCallout = shortDisplayText(targetText, 150);
  const eyebrow = sceneEyebrow(payload, "SOURCE VIEW");
  const sourceLabel = textValue(payload.source_label) || textValue(asset.capture?.domain);
  const image = asset.asset_data_uri || "";
  const editorial = isEditorialMinimal(spec.visual_style);
  const colors = editorialStyle(spec.visual_style);

  return (
    <AbsoluteFill style={{ fontFamily: editorial ? colors.sansFont : font.family, color: editorial ? colors.text : palette.text, background: editorial ? colors.background : palette.bg }}>
      {editorial ? (
        <AbsoluteFill style={{ opacity: 0.24, backgroundImage: "linear-gradient(rgba(23,22,17,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(23,22,17,0.025) 1px, transparent 1px)", backgroundSize: "72px 72px" }} />
      ) : (
        <MotionBackground motif="newsroom_grid" />
      )}
      <div style={{ position: "absolute", top: 42, left: 78, right: 78, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          {eyebrow && <div style={{ color: editorial ? colors.accent : palette.cyan, fontSize: 25, fontWeight: 900, letterSpacing: "0.16em", textTransform: "uppercase" }}>{eyebrow}</div>}
          <div style={{ marginTop: eyebrow ? 12 : 0, maxWidth: 1370, fontFamily: editorial ? colors.editorialFont : font.family, fontSize: readableTitleSize(headline, editorial ? 60 : 54), lineHeight: 0.96, fontWeight: editorial ? 700 : 950, letterSpacing: "-0.045em" }}>{headline}</div>
        </div>
        {sourceLabel && <div style={{ color: editorial ? colors.muted : palette.muted, fontSize: 24, fontWeight: 800, padding: editorial ? "8px 0" : "14px 20px", borderBottom: editorial ? `3px solid ${colors.accent}` : undefined, border: editorial ? undefined : "1px solid rgba(255,255,255,0.18)", borderRadius: editorial ? 0 : 999 }}>{sourceLabel}</div>}
      </div>

      <div style={{ position: "absolute", left: 76, right: 76, top: 190, bottom: 66, borderRadius: editorial ? 12 : 34, overflow: "hidden", border: editorial ? `1px solid ${colors.text}38` : "1px solid rgba(255,255,255,0.2)", background: editorial ? "#fffdfa" : palette.panelStrong, boxShadow: editorial ? "0 28px 80px rgba(42,35,25,0.18)" : "0 40px 130px rgba(0,0,0,0.55)", transform: `translateY(${interpolate(p, [0, 1], [34, 0])}px)`, opacity: clamp01(p) }}>
        <div style={{ height: 54, display: "flex", alignItems: "center", gap: 12, paddingLeft: 22, background: editorial ? "#e9e1d5" : "#111a27", borderBottom: editorial ? `1px solid ${colors.text}24` : "1px solid rgba(255,255,255,0.12)" }}>
          <span style={{ width: 15, height: 15, borderRadius: 99, background: "#ff5f57" }} />
          <span style={{ width: 15, height: 15, borderRadius: 99, background: "#ffbd2e" }} />
          <span style={{ width: 15, height: 15, borderRadius: 99, background: "#28c840" }} />
          <span style={{ marginLeft: 16, color: editorial ? colors.muted : palette.muted, fontSize: 20, fontWeight: 700 }}>{textValue(payload.url).replace(/^https?:\/\//, "").slice(0, 88)}</span>
        </div>
        {image ? (
          <Img src={image} style={{ width: "100%", height: "calc(100% - 54px)", objectFit: "cover", transform: `scale(${imageScale})`, transformOrigin: continuationIndex === 1 ? "center 28%" : "center 66%" }} />
        ) : (
          <div style={{ height: "calc(100% - 54px)", display: "flex", alignItems: "center", justifyContent: "center", color: editorial ? colors.muted : palette.muted, fontSize: 46, fontWeight: 900 }}>
            SOURCE SCREENSHOT UNAVAILABLE
          </div>
        )}
        <div style={{ position: "absolute", top: 54, bottom: 0, left: scanX, width: 190, background: editorial ? `linear-gradient(90deg, transparent, ${colors.accent}22, transparent)` : "linear-gradient(90deg, transparent, rgba(99,215,255,0.22), transparent)", filter: "blur(3px)" }} />
      </div>

      {targetCallout && (
        <div style={{ position: "absolute", left: 130, right: 130, bottom: 84, padding: "18px 28px", borderRadius: editorial ? 6 : 22, background: editorial ? "rgba(255,253,250,0.94)" : "rgba(7,13,22,0.88)", border: editorial ? `1px solid ${colors.text}33` : `1px solid ${palette.cyan}88`, borderLeft: editorial ? `8px solid ${colors.accent}` : undefined, boxShadow: editorial ? "0 14px 42px rgba(42,35,25,0.18)" : "0 18px 58px rgba(0,0,0,0.42)", color: editorial ? colors.text : "#ecf7ff", fontSize: 30, lineHeight: 1.12, fontWeight: editorial ? 700 : 820, textAlign: "center" }}>
          {targetCallout}
        </div>
      )}
    </AbsoluteFill>
  );
};
