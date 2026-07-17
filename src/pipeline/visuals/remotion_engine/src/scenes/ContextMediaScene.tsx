import React from "react";
import { AbsoluteFill, Img, Loop, OffthreadVideo, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { VisualSceneSpec } from "./types";
import { editorialStyle, font, isEditorialMinimal, palette, readableTitleSize, textValue } from "./style";

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
  const continuationCount = Math.max(1, Number(payload.continuation_count || 1));
  const continuationIndex = Math.min(
    continuationCount,
    Math.max(1, Number(payload.continuation_index || 1)),
  );
  const phaseStart = (continuationIndex - 1) / continuationCount;
  const phaseEnd = continuationIndex / continuationCount;
  const scale = interpolate(
    progress,
    [0, 1],
    isVideo
      ? [1.04 + phaseStart * 0.08, 1.04 + phaseEnd * 0.08]
      : [1.02 + phaseStart * 0.13, 1.02 + phaseEnd * 0.13],
  );
  const panDirection = continuationIndex % 2 === 1 ? 1 : -1;
  const panX = interpolate(progress, [0, 1], [-1.8 * panDirection, 1.8 * panDirection]);
  const headline = textValue(payload.overlay_headline);
  const showOverlay = payload.show_overlay === true && Boolean(headline);
  const clipSeconds = Number(asset.media?.duration_seconds || 0);
  const loopFrames = Math.max(1, Math.round((clipSeconds > 0 ? clipSeconds : spec.duration_seconds) * fps));
  const editorial = isEditorialMinimal(spec.visual_style);
  const editorialColors = editorialStyle(spec.visual_style);

  return (
    <AbsoluteFill style={{ background: editorial ? editorialColors.background : palette.bg, color: editorial ? editorialColors.text : palette.text, fontFamily: editorial ? editorialColors.sansFont : font.family, overflow: "hidden" }}>
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

      <AbsoluteFill style={{ background: editorial ? "linear-gradient(180deg, rgba(15,13,10,0.03) 0%, rgba(15,13,10,0.02) 48%, rgba(15,13,10,0.68) 100%)" : "linear-gradient(180deg, rgba(4,8,14,0.08) 0%, rgba(4,8,14,0.04) 44%, rgba(4,8,14,0.74) 100%)" }} />
      <div style={{ position: "absolute", left: editorial ? 54 : 0, top: editorial ? 54 : 0, bottom: editorial ? undefined : 0, width: editorial ? 150 : 14, height: editorial ? 8 : undefined, background: editorial ? editorialColors.accent : `linear-gradient(180deg, ${palette.cyan}, ${palette.green})`, opacity: 0.86 }} />

      {showOverlay && (
        <div style={{ position: "absolute", left: 82, bottom: 72, maxWidth: 1180, transform: `translateY(${interpolate(enter, [0, 1], [30, 0])}px)`, opacity: enter }}>
          <div style={{ fontFamily: editorial ? editorialColors.editorialFont : font.family, fontSize: readableTitleSize(headline, editorial ? 74 : 68), lineHeight: 0.96, fontWeight: editorial ? 700 : 950, letterSpacing: "-0.045em", color: editorial ? "#fffaf2" : palette.text, textShadow: "0 5px 28px rgba(0,0,0,0.8)" }}>
            {headline}
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
};
