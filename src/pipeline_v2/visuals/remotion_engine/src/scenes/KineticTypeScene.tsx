import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette } from "./style";

const listValue = (value: unknown) => (Array.isArray(value) ? value.map(String).filter(Boolean) : []);
const textValue = (value: unknown) => (typeof value === "string" ? value : "");

export const KineticTypeScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const phrases = listValue(payload.phrases).slice(0, 3);
  const phrase = phrases[0] || spec.scene.script_excerpt || "AI NEWS SHIFT";
  const emphasis = listValue(payload.emphasis_words);
  const motif = textValue(payload.background_motif) || "newsroom_grid";
  const p = spring({ fps, frame, config: { damping: 18, stiffness: 125, mass: 0.72 } });
  const words = phrase.split(/\s+/).slice(0, 11);

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={motif} />
      <div style={{ position: "absolute", left: 100, top: 86, color: palette.amber, fontSize: 26, fontWeight: 900, letterSpacing: "0.2em" }}>KEY POINT</div>
      <div style={{ position: "absolute", left: 106, right: 106, top: 220, display: "flex", flexWrap: "wrap", gap: "20px 26px", alignItems: "center" }}>
        {words.map((word, index) => {
          const start = 16 + index * 5;
          const opacity = clamp01(interpolate(frame, [start, start + 10], [0, 1], { extrapolateRight: "clamp" }));
          const y = interpolate(opacity, [0, 1], [42, 0]);
          const isHot = emphasis.some((item) => word.toLowerCase().replace(/[^a-z0-9]/g, "").includes(item.toLowerCase().replace(/[^a-z0-9]/g, "")));
          return (
            <span key={`${word}-${index}`} style={{ opacity, transform: `translateY(${y}px) scale(${interpolate(p, [0, 1], [0.98, 1])})`, fontSize: isHot ? 124 : 104, lineHeight: 0.92, fontWeight: 950, letterSpacing: "-0.07em", color: isHot ? palette.cyan : palette.text, textShadow: isHot ? "0 0 34px rgba(99,215,255,0.35)" : "none" }}>
              {word}
            </span>
          );
        })}
      </div>
      {phrases[1] && (
        <div style={{ position: "absolute", left: 112, right: 112, bottom: 126, color: "#cbd8e8", fontSize: 42, lineHeight: 1.08, fontWeight: 760, opacity: clamp01(interpolate(frame, [64, 88], [0, 1], { extrapolateRight: "clamp" })) }}>
          {phrases[1]}
        </div>
      )}
      <div style={{ position: "absolute", left: 112, right: 112, bottom: 68, height: 4, background: "rgba(255,255,255,0.10)", borderRadius: 99 }}>
        <div style={{ height: 4, width: `${interpolate(frame, [0, 150], [5, 100], { extrapolateRight: "clamp" })}%`, background: `linear-gradient(90deg, ${palette.cyan}, ${palette.amber})`, borderRadius: 99 }} />
      </div>
    </AbsoluteFill>
  );
};

