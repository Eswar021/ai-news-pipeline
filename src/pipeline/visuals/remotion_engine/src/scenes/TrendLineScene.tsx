import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, listValue, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

const pointsForDirection = (direction: string) => {
  if (direction === "falling") {
    return "120,210 310,235 505,275 705,330 910,390 1110,460";
  }
  if (direction === "volatile") {
    return "120,430 280,270 440,360 600,210 760,320 930,180 1110,250";
  }
  if (direction === "pressure_building") {
    return "120,455 315,430 510,395 705,330 910,240 1110,120";
  }
  if (direction === "flat_then_jump") {
    return "120,430 340,425 560,420 760,330 930,190 1110,95";
  }
  return "120,440 320,385 515,320 710,255 910,175 1110,100";
};

export const TrendLineScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || "Momentum is shifting";
  const direction = textValue(payload.trend_direction) || "rising";
  const annotations = listValue(payload.annotations).slice(0, 3);
  const progress = clamp01(interpolate(frame, [18, 92], [0, 1], { extrapolateRight: "clamp" }));
  const glow = direction === "falling" ? palette.red : direction === "volatile" ? palette.amber : palette.green;
  const eyebrow = sceneEyebrow(payload, "MOMENTUM VIEW");

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "abstract_ai"} />
      {eyebrow && (
        <div style={{ position: "absolute", left: 94, top: 74, color: glow, fontSize: 24, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>
      )}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 126 : 96, fontSize: readableTitleSize(headline, 84), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>
      <svg viewBox="0 0 1280 620" style={{ position: "absolute", left: 110, right: 110, top: 262, height: 610, overflow: "visible" }}>
        {[0, 1, 2, 3].map((row) => (
          <line key={row} x1="90" x2="1160" y1={120 + row * 105} y2={120 + row * 105} stroke="rgba(255,255,255,0.10)" strokeWidth="2" />
        ))}
        <polyline points={pointsForDirection(direction)} fill="none" stroke={`${glow}40`} strokeWidth="34" strokeLinecap="round" strokeLinejoin="round" />
        <polyline
          points={pointsForDirection(direction)}
          fill="none"
          stroke={glow}
          strokeWidth="13"
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - progress}
          style={{ filter: `drop-shadow(0 0 26px ${glow}99)` }}
        />
        {annotations.map((item, index) => {
          const x = 260 + index * 310;
          const y = direction === "falling" ? 250 + index * 70 : 360 - index * 88;
          const opacity = clamp01(interpolate(frame, [70 + index * 14, 86 + index * 14], [0, 1], { extrapolateRight: "clamp" }));
          return (
            <g key={`${item}-${index}`} opacity={opacity}>
              <circle cx={x} cy={y} r="13" fill={index % 2 === 0 ? palette.cyan : palette.amber} />
              <foreignObject x={x + 28} y={y - 42} width="340" height="100">
                <div style={{ color: palette.text, fontSize: 32, lineHeight: 1.02, fontWeight: 880, letterSpacing: "-0.025em" }}>{item}</div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
      {payload.show_axis_caption === true && (textValue(payload.y_axis_label) || textValue(payload.x_axis_label)) && (
        <div style={{ position: "absolute", left: 112, bottom: 72, color: palette.muted, fontSize: 25, fontWeight: 760 }}>
          {textValue(payload.y_axis_label) || "Momentum"} over {textValue(payload.x_axis_label) || "time"}
        </div>
      )}
    </AbsoluteFill>
  );
};
