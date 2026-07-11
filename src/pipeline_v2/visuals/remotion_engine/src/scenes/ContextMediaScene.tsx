import React from "react";
import { AbsoluteFill, Img, Loop, OffthreadVideo, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { VisualSceneSpec } from "./types";
import { font, palette, readableTitleSize, textValue } from "./style";

export const ContextMediaScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const isVideo = spec.scene.render_kind === "broll_video_scene";
  const imageSource = asset.asset_data_uri || "";
  const videoSource = asset.asset_public_path ? staticFile(asset.asset_public_path) : "";
  const enter = spring({ fps, frame, config: { damping: 22, stiffness: 90, mass: 0.9 } });
  const progress = Math.max(0, Math.min(1, frame / Math.max(1, durationInFrames - 1)));
  const scale = interpolate(progress, [0, 1], isVideo ? [1.04, 1.1] : [1.02, 1.13]);
  const panX = interpolate(progress, [0, 1], [-1.4, 1.4]);
  const headline = textValue(payload.overlay_headline);
  const showOverlay = payload.show_overlay === true && Boolean(headline);
  const clipSeconds = Number(asset.media?.duration_seconds || 0);
  const loopFrames = Math.max(1, Math.round((clipSeconds > 0 ? clipSeconds : spec.duration_seconds) * fps));

  return (
    <AbsoluteFill style={{ background: palette.bg, color: palette.text, fontFamily: font.family, overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: -18, transform: `translateX(${panX}%) scale(${scale})`, opacity: interpolate(enter, [0, 1], [0.35, 1]) }}>
        {isVideo && videoSource ? (
          <Loop durationInFrames={loopFrames}>
            <OffthreadVideo
              src={videoSource}
              muted
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          </Loop>
        ) : imageSource ? (
          <Img src={imageSource} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          <AbsoluteFill style={{ display: "flex", alignItems: "center", justifyContent: "center", color: palette.muted, fontSize: 42, fontWeight: 850 }}>
            CONTEXT MEDIA UNAVAILABLE
          </AbsoluteFill>
        )}
      </div>

      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(4,8,14,0.08) 0%, rgba(4,8,14,0.04) 44%, rgba(4,8,14,0.74) 100%)" }} />
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 14, background: `linear-gradient(180deg, ${palette.cyan}, ${palette.green})`, opacity: 0.86 }} />

      {showOverlay && (
        <div style={{ position: "absolute", left: 82, bottom: 72, maxWidth: 1180, transform: `translateY(${interpolate(enter, [0, 1], [30, 0])}px)`, opacity: enter }}>
          <div style={{ fontSize: readableTitleSize(headline, 68), lineHeight: 0.96, fontWeight: 950, letterSpacing: "-0.045em", textShadow: "0 5px 28px rgba(0,0,0,0.8)" }}>
            {headline}
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
};
