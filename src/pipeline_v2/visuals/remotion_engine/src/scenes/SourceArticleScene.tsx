import React from "react";
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette } from "./style";

const textValue = (value: unknown) => (typeof value === "string" ? value : "");

export const SourceArticleScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const p = spring({ fps, frame, config: { damping: 20, stiffness: 110, mass: 0.7 } });
  const imageScale = interpolate(frame, [0, durationInFrames], [1.02, 1.11]);
  const scanX = interpolate(frame, [25, durationInFrames - 18], [-360, 1360], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const headline = textValue(payload.overlay_headline) || spec.scene.script_excerpt || "Source context";
  const targetText = textValue(payload.target_text);
  const image = asset.asset_data_uri || "";

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif="newsroom_grid" />
      <div style={{ position: "absolute", top: 62, left: 78, right: 78, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ color: palette.cyan, fontSize: 25, fontWeight: 900, letterSpacing: "0.18em" }}>SOURCE VIEW</div>
          <div style={{ marginTop: 16, maxWidth: 1260, fontSize: 58, lineHeight: 0.94, fontWeight: 950, letterSpacing: "-0.045em" }}>{headline}</div>
        </div>
        <div style={{ color: palette.muted, fontSize: 24, fontWeight: 800, padding: "14px 20px", border: "1px solid rgba(255,255,255,0.18)", borderRadius: 999 }}>
          {textValue(asset.capture?.domain) || "ARTICLE"}
        </div>
      </div>

      <div style={{ position: "absolute", left: 90, right: 90, top: 250, bottom: 114, borderRadius: 34, overflow: "hidden", border: "1px solid rgba(255,255,255,0.2)", background: palette.panelStrong, boxShadow: "0 40px 130px rgba(0,0,0,0.55)", transform: `translateY(${interpolate(p, [0, 1], [34, 0])}px)`, opacity: clamp01(p) }}>
        <div style={{ height: 54, display: "flex", alignItems: "center", gap: 12, paddingLeft: 22, background: "#111a27", borderBottom: "1px solid rgba(255,255,255,0.12)" }}>
          <span style={{ width: 15, height: 15, borderRadius: 99, background: "#ff5f57" }} />
          <span style={{ width: 15, height: 15, borderRadius: 99, background: "#ffbd2e" }} />
          <span style={{ width: 15, height: 15, borderRadius: 99, background: "#28c840" }} />
          <span style={{ marginLeft: 16, color: palette.muted, fontSize: 20, fontWeight: 700 }}>{textValue(payload.url).replace(/^https?:\/\//, "").slice(0, 88)}</span>
        </div>
        {image ? (
          <Img src={image} style={{ width: "100%", height: "calc(100% - 54px)", objectFit: "cover", transform: `scale(${imageScale})`, transformOrigin: "center center" }} />
        ) : (
          <div style={{ height: "calc(100% - 54px)", display: "flex", alignItems: "center", justifyContent: "center", color: palette.muted, fontSize: 46, fontWeight: 900 }}>
            SOURCE SCREENSHOT UNAVAILABLE
          </div>
        )}
        <div style={{ position: "absolute", top: 54, bottom: 0, left: scanX, width: 190, background: "linear-gradient(90deg, transparent, rgba(99,215,255,0.22), transparent)", filter: "blur(3px)" }} />
      </div>

      <div style={{ position: "absolute", left: 112, right: 112, bottom: 42, display: "flex", gap: 18, alignItems: "center" }}>
        <div style={{ color: "#061016", background: palette.cyan, borderRadius: 999, padding: "11px 17px", fontWeight: 950, fontSize: 22 }}>HIGHLIGHT</div>
        <div style={{ color: "#d8e4f2", fontSize: 26, fontWeight: 750, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{targetText}</div>
      </div>
    </AbsoluteFill>
  );
};

