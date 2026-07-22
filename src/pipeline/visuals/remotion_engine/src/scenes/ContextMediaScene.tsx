import React from "react";
import { AbsoluteFill, Img, Loop, OffthreadVideo, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { VisualSceneSpec } from "./types";
import { editorialStyle, listValue, readableBodySize, readableTitleSize, shortDisplayText, textValue } from "./style";

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
  const annotations = listValue(payload.annotations || payload.callouts).slice(0, 3);
  const clipSeconds = Number(asset.media?.duration_seconds || 0);
  const loopFrames = Math.max(1, Math.round((clipSeconds > 0 ? clipSeconds : spec.duration_seconds) * fps));
  const editorialColors = editorialStyle(spec.visual_style);

  return (
    <AbsoluteFill style={{ background: editorialColors.background, color: editorialColors.text, fontFamily: editorialColors.sansFont, overflow: "hidden" }}>
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
          <AbsoluteFill style={{ display: "flex", alignItems: "center", justifyContent: "center", color: editorialColors.muted, fontSize: 42, fontWeight: 850 }}>
            CONTEXT MEDIA UNAVAILABLE
          </AbsoluteFill>
        )}
      </div>

      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(15,13,10,0.03) 0%, rgba(15,13,10,0.02) 48%, rgba(15,13,10,0.68) 100%)" }} />
      {annotations.length > 0 && (
        <div style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: 850, background: "linear-gradient(90deg, transparent, rgba(7,10,13,0.72) 30%, rgba(7,10,13,0.94))" }} />
      )}
      <div style={{ position: "absolute", left: 54, top: 54, width: 150, height: 8, background: editorialColors.accent, opacity: 0.86 }} />

      {showOverlay && (
        <div style={{ position: "absolute", left: 82, bottom: 72, maxWidth: 1180, transform: `translateY(${interpolate(enter, [0, 1], [30, 0])}px)`, opacity: enter }}>
          <div style={{ fontFamily: editorialColors.editorialFont, fontSize: readableTitleSize(headline, 74), lineHeight: 0.96, fontWeight: 700, letterSpacing: "-0.045em", color: "#fffaf2", textShadow: "0 5px 28px rgba(0,0,0,0.8)" }}>
            {headline}
          </div>
        </div>
      )}

      {annotations.length > 0 && (
        <div style={{ position: "absolute", right: 82, top: 112, bottom: showOverlay ? 400 : 112, width: 570, display: "flex", flexDirection: "column", justifyContent: "center", gap: 32 }}>
          {annotations.map((annotation, index) => {
            const reveal = Math.max(0, Math.min(1, interpolate(frame, [18 + index * 16, 36 + index * 16], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })));
            const copy = shortDisplayText(annotation, 88);
            return (
              <div key={`${annotation}-${index}`} style={{ display: "grid", gridTemplateColumns: "18px 1fr", gap: 20, alignItems: "start", opacity: reveal, transform: `translateX(${interpolate(reveal, [0, 1], [48, 0])}px)` }}>
                <div style={{ marginTop: 12, width: 15, height: 15, borderRadius: 99, background: editorialColors.accent, boxShadow: `0 0 22px ${editorialColors.accent}88` }} />
                <div style={{ color: "#fffaf2", fontSize: readableBodySize(copy, 34), lineHeight: 1.09, fontWeight: 790, letterSpacing: "-0.025em", textShadow: "0 4px 24px rgba(0,0,0,0.78)" }}>{copy}</div>
              </div>
            );
          })}
        </div>
      )}
    </AbsoluteFill>
  );
};
