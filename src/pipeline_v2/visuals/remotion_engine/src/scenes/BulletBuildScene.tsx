import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { beatList, clamp01, font, listValue, palette, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

export const BulletBuildScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "What changes next";
  const beats = beatList(payload.beats);
  const points = (listValue(payload.points).length ? listValue(payload.points) : beats.map((beat) => beat.text || "")).map((point) => shortDisplayText(point, 78)).slice(0, 4);
  const emphasis = [...listValue(payload.emphasis_words), ...beats.flatMap((beat) => beat.emphasis_words || [])];
  const motif = textValue(payload.background_motif) || "newsroom_grid";
  const eyebrow = sceneEyebrow(payload, "POINT BY POINT");
  const pulse = spring({ fps, frame, config: { damping: 18, stiffness: 120, mass: 0.7 } });

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={motif} />
      {eyebrow && (
        <div style={{ position: "absolute", left: 100, top: 72, color: palette.amber, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>
      )}
      <div style={{ position: "absolute", left: 100, right: 100, top: eyebrow ? 126 : 102, fontSize: readableTitleSize(headline, 86), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>
        {headline}
      </div>

      <div style={{ position: "absolute", left: 150, right: 150, top: 332, display: "flex", flexDirection: "column", gap: 30 }}>
        {points.map((point, index) => {
          const beatStartSeconds = beats[index]?.relative_start_seconds;
          const start = typeof beatStartSeconds === "number" ? Math.max(8, Math.round(beatStartSeconds * fps)) : 18 + index * 26;
          const opacity = clamp01(interpolate(frame, [start, start + 12], [0, 1], { extrapolateRight: "clamp" }));
          const y = interpolate(opacity, [0, 1], [42, 0]);
          const words = point.split(/\s+/);
          return (
            <div key={`${point}-${index}`} style={{ opacity, transform: `translateY(${y}px)`, display: "flex", alignItems: "center", gap: 24 }}>
              <div style={{ width: 82, height: 82, borderRadius: 28, display: "flex", alignItems: "center", justifyContent: "center", color: "#061016", background: index % 2 === 0 ? palette.cyan : palette.amber, fontSize: 34, fontWeight: 950, transform: `scale(${interpolate(pulse, [0, 1], [0.92, 1])})` }}>
                {index + 1}
              </div>
              <div style={{ flex: 1, padding: "25px 32px", borderRadius: 30, background: "rgba(255,255,255,0.082)", border: "1px solid rgba(255,255,255,0.14)", boxShadow: "0 28px 80px rgba(0,0,0,0.24)" }}>
                <div style={{ fontSize: 46, lineHeight: 1.02, fontWeight: 870, letterSpacing: "-0.04em" }}>
                  {words.map((word, wordIndex) => {
                    const normalized = word.toLowerCase().replace(/[^a-z0-9]/g, "");
                    const hot = emphasis.some((item) => normalized.includes(item.toLowerCase().replace(/[^a-z0-9]/g, "")));
                    return (
                      <span key={`${word}-${wordIndex}`} style={{ color: hot ? palette.cyan : palette.text }}>
                        {word}{wordIndex < words.length - 1 ? " " : ""}
                      </span>
                    );
                  })}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
