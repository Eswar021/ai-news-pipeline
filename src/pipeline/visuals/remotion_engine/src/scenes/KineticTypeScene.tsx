import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, listValue, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

export const KineticTypeScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const phrases = listValue(payload.phrases).slice(0, 3);
  const phrase = phrases[0] || spec.scene.script_excerpt || "";
  const emphasis = listValue(payload.emphasis_words);
  const motif = textValue(payload.background_motif) || "newsroom_grid";
  const eyebrow = sceneEyebrow(payload, "KEY POINT");
  const p = spring({ fps, frame, config: { damping: 18, stiffness: 125, mass: 0.72 } });
  const words = phrase.split(/\s+/).slice(0, 11);
  const titleSize = readableTitleSize(phrase, 116);

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={motif} />
      {eyebrow && (
        <div style={{ position: "absolute", left: 110, top: 82, color: palette.amber, fontSize: 24, fontWeight: 900, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>
      )}
      <div style={{ position: "absolute", left: 118, right: 118, top: phrases[1] ? 230 : 286, display: "flex", flexWrap: "wrap", gap: "20px 28px", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
        {words.map((word, index) => {
          const start = 16 + index * 5;
          const opacity = clamp01(interpolate(frame, [start, start + 10], [0, 1], { extrapolateRight: "clamp" }));
          const y = interpolate(opacity, [0, 1], [42, 0]);
          const isHot = emphasis.some((item) => word.toLowerCase().replace(/[^a-z0-9]/g, "").includes(item.toLowerCase().replace(/[^a-z0-9]/g, "")));
          return (
            <span key={`${word}-${index}`} style={{ opacity, transform: `translateY(${y}px) scale(${interpolate(p, [0, 1], [0.98, 1])})`, fontSize: isHot ? titleSize * 1.1 : titleSize, lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.075em", color: isHot ? palette.cyan : palette.text, textShadow: isHot ? "0 0 34px rgba(99,215,255,0.35)" : "none" }}>
              {word}
            </span>
          );
        })}
      </div>
      {phrases[1] && (
        <div style={{ position: "absolute", left: 190, right: 190, top: 540, color: "#dce8f6", fontSize: readableTitleSize(phrases[1], 76), lineHeight: 0.98, fontWeight: 880, textAlign: "center", letterSpacing: "-0.055em", opacity: clamp01(interpolate(frame, [58, 82], [0, 1], { extrapolateRight: "clamp" })), textShadow: "0 0 30px rgba(255,255,255,0.12)" }}>
          {phrases[1]}
        </div>
      )}
      {payload.show_progress_line === true && (
        <div style={{ position: "absolute", left: 420, right: 420, bottom: 82, height: 4, background: "rgba(255,255,255,0.10)", borderRadius: 99 }}>
          <div style={{ height: 4, width: `${interpolate(frame, [0, 150], [5, 100], { extrapolateRight: "clamp" })}%`, background: `linear-gradient(90deg, ${palette.cyan}, ${palette.amber})`, borderRadius: 99 }} />
        </div>
      )}
    </AbsoluteFill>
  );
};
