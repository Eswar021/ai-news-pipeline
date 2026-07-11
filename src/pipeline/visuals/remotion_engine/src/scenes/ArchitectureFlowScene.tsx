import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableBodySize, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

type StepItem = { label?: string; detail?: string };

const stepList = (value: unknown): StepItem[] =>
  Array.isArray(value)
    ? value
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
        .map((item) => ({ label: textValue(item.label), detail: textValue(item.detail) }))
        .filter((item) => item.label)
    : [];

const layoutFor = (count: number) => {
  if (count <= 4) {
    const cardWidth = count <= 3 ? 420 : 360;
    const gap = count <= 3 ? 86 : 52;
    const startX = 960 - (count * cardWidth + (count - 1) * gap) / 2;
    return {
      cardWidth,
      cardHeight: 232,
      points: Array.from({ length: count }, (_, index) => ({ x: startX + index * (cardWidth + gap), y: 300 })),
    };
  }
  const cardWidth = 430;
  const cardHeight = 178;
  const topCount = Math.ceil(count / 2);
  const bottomCount = count - topCount;
  const topStart = 960 - (topCount * cardWidth + (topCount - 1) * 60) / 2;
  const bottomStart = 960 - (bottomCount * cardWidth + Math.max(0, bottomCount - 1) * 60) / 2;
  return {
    cardWidth,
    cardHeight,
    points: Array.from({ length: count }, (_, index) => {
      if (index < topCount) {
        return { x: topStart + index * (cardWidth + 60), y: 220 };
      }
      const bottomIndex = index - topCount;
      return { x: bottomStart + bottomIndex * (cardWidth + 60), y: 530 };
    }),
  };
};

export const ArchitectureFlowScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || "How the system works";
  const steps = stepList(payload.steps).slice(0, 6);
  const active = textValue(payload.active_step_label) || steps[steps.length - 1]?.label || "Output";
  const eyebrow = sceneEyebrow(payload, "SYSTEM FLOW");
  const p = spring({ fps, frame, config: { damping: 18, stiffness: 105, mass: 0.72 } });
  const items = steps.length ? steps : [{ label: "Input" }, { label: "Model" }, { label: "Output" }];
  const layout = layoutFor(items.length);
  const { cardWidth, cardHeight, points } = layout;

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "newsroom_grid"} />
      {eyebrow && (
        <div style={{ position: "absolute", left: 92, top: 74, color: palette.amber, fontSize: 24, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>
      )}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 126 : 96, fontSize: readableTitleSize(headline, 82), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>
      <svg viewBox="0 0 1920 740" style={{ position: "absolute", left: 0, right: 0, top: 250, height: 760 }}>
        {items.slice(0, -1).map((step, index) => {
          const current = points[index];
          const next = points[index + 1];
          if (!current || !next) {
            return null;
          }
          const reveal = clamp01(interpolate(frame, [38 + index * 14, 58 + index * 14], [0, 1], { extrapolateRight: "clamp" }));
          const startX = current.x + cardWidth;
          const startY = current.y + cardHeight / 2;
          const endX = next.x;
          const endY = next.y + cardHeight / 2;
          const midX = startX + (endX - startX) * 0.5;
          const path = Math.abs(endY - startY) < 20
            ? `M ${startX + 12} ${startY} L ${endX - 18} ${endY}`
            : `M ${startX + 10} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX - 20} ${endY}`;
          return (
            <g key={`flow-line-${step.label}-${index}`} opacity={reveal}>
              <path d={path} fill="none" stroke={palette.cyan} strokeWidth="7" strokeLinecap="round" opacity={0.72} />
              <circle cx={startX + (endX - startX) * clamp01(interpolate(frame, [60 + index * 14, 100 + index * 14], [0, 1], { extrapolateRight: "clamp" }))} cy={startY + (endY - startY) * clamp01(interpolate(frame, [60 + index * 14, 100 + index * 14], [0, 1], { extrapolateRight: "clamp" }))} r="9" fill={palette.amber} />
            </g>
          );
        })}
        {items.map((step, index) => {
          const point = points[index] || { x: 960, y: 300 };
          const x = point.x;
          const y = point.y;
          const reveal = clamp01(interpolate(frame, [16 + index * 14, 34 + index * 14], [0, 1], { extrapolateRight: "clamp" }));
          const isActive = step.label === active || index === items.length - 1;
          const label = shortDisplayText(step.label || `Step ${index + 1}`, items.length <= 4 ? 30 : 24);
          const detail = shortDisplayText(step.detail || "", items.length <= 4 ? 62 : 48);
          return (
            <g key={`${step.label}-${index}`} opacity={reveal} transform={`translate(${x}, ${y + interpolate(reveal, [0, 1], [38, 0])}) scale(${interpolate(p, [0, 1], [0.98, 1])})`}>
              <rect width={cardWidth} height={cardHeight} rx="38" fill={isActive ? `${palette.cyan}2d` : "rgba(255,255,255,0.09)"} stroke={isActive ? palette.cyan : "rgba(255,255,255,0.18)"} strokeWidth="4" />
              <circle cx="58" cy="56" r="23" fill={index % 2 === 0 ? palette.cyan : palette.amber} />
              <text x="58" y="66" textAnchor="middle" fill="#061016" fontSize="28" fontWeight="950">{index + 1}</text>
              <foreignObject x="38" y="86" width={cardWidth - 76} height={cardHeight - 98}>
                <div style={{ height: "100%", display: "flex", flexDirection: "column", justifyContent: "center" }}>
                  <div style={{ color: palette.text, fontSize: readableBodySize(label, items.length <= 4 ? 43 : 35), lineHeight: 0.96, fontWeight: 940, letterSpacing: "-0.055em" }}>{label}</div>
                  {detail && <div style={{ marginTop: 14, color: "#d5e3f3", fontSize: readableBodySize(detail, items.length <= 4 ? 29 : 24), lineHeight: 1.08, fontWeight: 760 }}>{detail}</div>}
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
};
