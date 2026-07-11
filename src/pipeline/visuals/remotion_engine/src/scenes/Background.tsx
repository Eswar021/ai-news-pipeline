import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { palette } from "./style";

export const MotionBackground: React.FC<{ motif?: string }> = ({ motif = "newsroom_grid" }) => {
  const frame = useCurrentFrame();
  const drift = interpolate(frame, [0, 240], [0, 80], { extrapolateRight: "clamp" });
  const glow = motif === "device_glow" ? palette.cyan : motif === "abstract_ai" ? palette.amber : palette.green;
  return (
    <AbsoluteFill style={{ background: palette.bg, overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            `radial-gradient(circle at ${22 + drift / 18}% 22%, ${glow}42 0, transparent 24%),` +
            "radial-gradient(circle at 78% 12%, rgba(255,255,255,0.12) 0, transparent 25%)," +
            "linear-gradient(135deg, #07101a 0%, #101827 45%, #040609 100%)"
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.055) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)",
          backgroundSize: "74px 74px",
          transform: `translate(${drift * -0.25}px, ${drift * -0.15}px)`,
          opacity: 0.52
        }}
      />
      <div
        style={{
          position: "absolute",
          left: -180,
          bottom: -220,
          width: 560,
          height: 560,
          borderRadius: 999,
          background: `${glow}33`,
          filter: "blur(18px)"
        }}
      />
    </AbsoluteFill>
  );
};

