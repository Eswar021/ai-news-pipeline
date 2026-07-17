import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableBodySize, readableTitleSize, sceneEyebrow, textValue } from "./style";

export const TransitionStingerScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const label = textValue(payload.transition_label) || textValue(payload.headline) || spec.scene.script_excerpt || "";
  const subtitle = textValue(payload.subtitle);
  const motif = textValue(payload.background_motif) || "abstract_ai";
  const motionStyle = textValue(payload.motion_style) || "signal_wipe";
  const eyebrow = sceneEyebrow(payload, "SIGNAL SHIFT");
  const entrance = spring({ fps, frame, config: { damping: 13, stiffness: 120, mass: 0.7 } });
  const exit = clamp01(interpolate(frame, [durationInFrames - 18, durationInFrames - 1], [0, 1], { extrapolateLeft: "clamp" }));
  const sweep = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [-420, 420], { extrapolateRight: "clamp" });
  const pulse = Math.sin(frame / 7) * 0.5 + 0.5;
  const accent = motionStyle === "radar_ping" ? palette.green : motionStyle === "glitch_snap" ? palette.red : palette.cyan;

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text, overflow: "hidden" }}>
      <MotionBackground motif={motif} />
      <div
        style={{
          position: "absolute",
          inset: -100,
          transform: `translateX(${sweep}px) rotate(-12deg)`,
          background: `linear-gradient(90deg, transparent 0%, ${accent}00 30%, ${accent}55 48%, rgba(255,255,255,0.52) 52%, ${accent}66 58%, transparent 100%)`,
          filter: "blur(2px)",
          opacity: 0.88 - exit * 0.7,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: "50%",
          width: 640,
          height: 640,
          borderRadius: 999,
          transform: `translate(-50%, -50%) scale(${0.74 + entrance * 0.34 + pulse * 0.025})`,
          border: `2px solid ${accent}44`,
          boxShadow: `0 0 ${80 + pulse * 60}px ${accent}55, inset 0 0 70px ${accent}24`,
          opacity: 0.92 - exit * 0.88,
        }}
      />
      {[0, 1, 2, 3].map((index) => {
        const offset = index * 52;
        const opacity = clamp01(interpolate(frame, [6 + offset / 4, 24 + offset / 4], [0, 1], { extrapolateRight: "clamp" })) * (1 - exit);
        return (
          <div
            key={index}
            style={{
              position: "absolute",
              left: 180 + index * 56,
              right: 180 + (3 - index) * 48,
              top: 226 + index * 126,
              height: 2,
              background: `linear-gradient(90deg, transparent, ${accent}, transparent)`,
              opacity,
              transform: `translateX(${interpolate(entrance, [0, 1], [-80 + index * 22, 0])}px)`,
            }}
          />
        );
      })}
      <div
        style={{
          position: "absolute",
          left: 120,
          right: 120,
          top: 284,
          textAlign: "center",
          opacity: 1 - exit,
          transform: `translateY(${interpolate(entrance, [0, 1], [46, 0])}px) scale(${interpolate(entrance, [0, 1], [0.94, 1])})`,
        }}
      >
        {eyebrow && (
          <div style={{ color: accent, fontSize: 24, fontWeight: 950, letterSpacing: "0.22em", textTransform: "uppercase" }}>
            {eyebrow}
          </div>
        )}
        <div style={{ margin: `${eyebrow ? 24 : 0}px auto 0`, maxWidth: 1500, fontSize: readableTitleSize(label, 102), lineHeight: 0.92, fontWeight: 950, letterSpacing: "-0.06em" }}>
          {label}
        </div>
        <div style={{ margin: "30px auto 0", width: 1120, maxWidth: "78%", color: "#dce8f6", fontSize: readableBodySize(subtitle, 38), lineHeight: 1.12, fontWeight: 760 }}>
          {subtitle}
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: "50%",
          bottom: 74,
          transform: "translateX(-50%)",
          display: "flex",
          gap: 12,
          opacity: 1 - exit,
        }}
      >
        {[0, 1, 2, 3, 4].map((index) => (
          <div
            key={index}
            style={{
              width: 58,
              height: 8,
              borderRadius: 999,
              background: index <= Math.floor((frame / Math.max(1, durationInFrames)) * 5) ? accent : "rgba(255,255,255,0.18)",
              boxShadow: index <= Math.floor((frame / Math.max(1, durationInFrames)) * 5) ? `0 0 20px ${accent}` : "none",
            }}
          />
        ))}
      </div>
    </AbsoluteFill>
  );
};
