import React from "react";
import {
  AbsoluteFill,
  Img,
  Loop,
  OffthreadVideo,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { EditorialCanvas } from "./EditorialCanvas";
import { VisualSceneSpec } from "./types";
import { clamp01, editorialStyle, listValue, textValue } from "./style";

const normalized = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");

export const StoryTransitionScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const colors = editorialStyle(spec.visual_style);
  const headline = textValue(payload.headline);
  const subtitle = textValue(payload.subtitle);
  const eyebrow = textValue(payload.eyebrow) || (textValue(payload.story_number) ? `STORY ${textValue(payload.story_number)}` : "NEXT STORY");
  const accentWords = new Set(listValue(payload.accent_words).map(normalized));
  const enter = spring({ fps, frame, config: { damping: 19, stiffness: 92, mass: 0.82 } });
  const titleSize = headline.length > 110 ? 72 : headline.length > 78 ? 84 : headline.length > 48 ? 98 : 116;
  const lineWidth = interpolate(enter, [0, 1], [0, 460]);
  const imageSource = asset.asset_data_uri || "";
  const videoSource = asset.asset_public_path ? staticFile(asset.asset_public_path) : "";
  const backgroundType = textValue(payload.background_media_type);
  const hasLogo = backgroundType === "logo" && Boolean(imageSource);
  const hasMedia = (backgroundType === "image" && Boolean(imageSource)) || (backgroundType === "video" && Boolean(videoSource));
  const progress = Math.max(0, Math.min(1, frame / Math.max(1, durationInFrames - 1)));
  const mediaScale = interpolate(progress, [0, 1], [1.02, 1.1]);
  const clipSeconds = Number(asset.media?.duration_seconds || 0);
  const loopFrames = Math.max(1, Math.round((clipSeconds > 0 ? clipSeconds : spec.duration_seconds) * fps));

  const titleBlock = (onMedia: boolean) => (
    <div
      style={{
        position: "absolute",
        left: 150,
        right: hasLogo ? 690 : 250,
        top: 145,
        bottom: 125,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        transform: `translateX(${interpolate(enter, [0, 1], [-42, 0])}px)`,
        opacity: clamp01(enter),
      }}
    >
      <div style={{ color: colors.accent, fontSize: 27, fontWeight: 850, letterSpacing: "0.2em", textTransform: "uppercase" }}>
        {eyebrow}
      </div>
      <div style={{ marginTop: 34, maxWidth: 1460, fontFamily: colors.editorialFont, fontSize: titleSize, lineHeight: 0.92, fontWeight: 700, letterSpacing: "-0.052em" }}>
        {headline.split(/\s+/).map((word, index) => (
          <span key={`${word}-${index}`} style={{ display: "inline-block", color: accentWords.has(normalized(word)) ? colors.accent : onMedia ? "#fffaf2" : colors.text, marginRight: "0.2em", textShadow: onMedia ? "0 5px 32px rgba(0,0,0,0.78)" : "none" }}>
            {word}
          </span>
        ))}
      </div>
      <div style={{ marginTop: 38, width: lineWidth, height: 7, background: colors.accent }} />
      {subtitle && <div style={{ marginTop: 28, color: onMedia ? "rgba(255,250,242,0.82)" : colors.muted, fontSize: 34, lineHeight: 1.15, fontWeight: 600, textShadow: onMedia ? "0 3px 22px rgba(0,0,0,0.72)" : "none" }}>{subtitle}</div>}
    </div>
  );

  if (hasMedia) {
    return (
      <AbsoluteFill style={{ background: "#14120f", overflow: "hidden", fontFamily: colors.sansFont }}>
        <div style={{ position: "absolute", inset: -24, transform: `scale(${mediaScale})` }}>
          {backgroundType === "video" ? (
            <Loop durationInFrames={loopFrames}>
              <OffthreadVideo src={videoSource} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            </Loop>
          ) : (
            <Img src={imageSource} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          )}
        </div>
        <AbsoluteFill style={{ background: "linear-gradient(90deg, rgba(15,13,10,0.91) 0%, rgba(15,13,10,0.69) 52%, rgba(15,13,10,0.18) 100%)" }} />
        {titleBlock(true)}
      </AbsoluteFill>
    );
  }

  if (hasLogo) {
    return (
      <EditorialCanvas spec={spec} accentPosition="right">
        <div style={{ position: "absolute", right: 150, top: 235, width: 470, height: 470, display: "flex", alignItems: "center", justifyContent: "center", opacity: clamp01(enter), transform: `scale(${interpolate(enter, [0, 1], [0.82, 1])})` }}>
          <Img src={imageSource} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
        </div>
        {titleBlock(false)}
      </EditorialCanvas>
    );
  }

  return (
    <EditorialCanvas spec={spec} accentPosition="right">
      <div
        style={{
          position: "absolute",
          right: 110,
          top: 80,
          color: `${colors.accent}18`,
          fontFamily: colors.editorialFont,
          fontSize: 330,
          fontWeight: 700,
          lineHeight: 1,
        }}
      >
        {textValue(payload.story_number)}
      </div>
      {titleBlock(false)}
    </EditorialCanvas>
  );
};
