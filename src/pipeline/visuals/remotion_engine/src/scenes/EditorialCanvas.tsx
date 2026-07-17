import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { VisualSceneSpec } from "./types";
import { editorialStyle } from "./style";

export const EditorialCanvas: React.FC<{
  spec: VisualSceneSpec;
  children: React.ReactNode;
  accentPosition?: "left" | "right" | "center";
}> = ({ spec, children, accentPosition = "right" }) => {
  const frame = useCurrentFrame();
  const colors = editorialStyle(spec.visual_style);
  const drift = interpolate(frame, [0, Math.max(1, spec.fps * spec.duration_seconds)], [-12, 16]);
  const accentLeft = accentPosition === "left" ? "-8%" : accentPosition === "center" ? "36%" : "68%";

  return (
    <AbsoluteFill
      style={{
        background: colors.background,
        color: colors.text,
        fontFamily: colors.sansFont,
        overflow: "hidden",
      }}
    >
      <AbsoluteFill
        style={{
          opacity: 0.28,
          backgroundImage:
            "linear-gradient(rgba(23,22,17,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(23,22,17,0.028) 1px, transparent 1px)",
          backgroundSize: "72px 72px",
          transform: `translateX(${drift * 0.12}px)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 760,
          height: 760,
          left: accentLeft,
          top: -320,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${colors.accent}22 0%, ${colors.accent}09 38%, transparent 70%)`,
          transform: `translate(${drift}px, ${drift * 0.25}px)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 72,
          right: 72,
          bottom: 48,
          height: 2,
          background: `linear-gradient(90deg, ${colors.accent}, ${colors.text}20 36%, transparent 88%)`,
        }}
      />
      {children}
    </AbsoluteFill>
  );
};

