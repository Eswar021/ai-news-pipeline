import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, listValue, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type SignalItem = {
  label?: string;
  strength?: number | string;
  detail?: string;
};

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const numberValue = (value: unknown, fallback: number) => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  const parsed = Number(String(value ?? "").replace(/[^0-9.-]/g, ""));
  return Number.isFinite(parsed) ? parsed : fallback;
};

const signalsFromPayload = (value: unknown): SignalItem[] => {
  const objects = objectList<Record<string, unknown>>(value)
    .map((item) => ({
      label: textValue(item.label) || textValue(item.name),
      strength: item.strength as number | string | undefined,
      detail: textValue(item.detail) || textValue(item.description),
    }))
    .filter((item) => item.label && item.strength !== undefined);
  if (objects.length) {
    return objects.slice(0, 6);
  }
  return [];
};

export const SignalRadarScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "SIGNAL RADAR");
  const scanLabel = textValue(payload.scan_label);
  const signals = signalsFromPayload(payload.signals);
  const sweep = interpolate(frame, [0, durationInFrames], [0, 360]);
  const center = { x: 620, y: 390 };

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "abstract_ai"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.green, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, top: eyebrow ? 122 : 92, width: 760, fontSize: readableTitleSize(headline, 82), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>
      <svg viewBox="0 0 1280 780" style={{ position: "absolute", left: 90, top: 240, height: 780, width: 1280 }}>
        {[1, 2, 3, 4].map((ring) => <circle key={ring} cx={center.x} cy={center.y} r={ring * 92} fill="none" stroke="rgba(141,247,189,0.18)" strokeWidth="3" />)}
        <line x1={center.x - 410} y1={center.y} x2={center.x + 410} y2={center.y} stroke="rgba(255,255,255,0.10)" strokeWidth="3" />
        <line x1={center.x} y1={center.y - 410} x2={center.x} y2={center.y + 410} stroke="rgba(255,255,255,0.10)" strokeWidth="3" />
        <g transform={`rotate(${sweep} ${center.x} ${center.y})`}>
          <path d={`M ${center.x} ${center.y} L ${center.x + 390} ${center.y - 34} L ${center.x + 390} ${center.y + 34} Z`} fill="rgba(141,247,189,0.20)" />
          <line x1={center.x} y1={center.y} x2={center.x + 410} y2={center.y} stroke={palette.green} strokeWidth="5" strokeLinecap="round" />
        </g>
        {signals.map((signal, index) => {
          const angle = (-120 + index * (240 / Math.max(1, signals.length - 1))) * (Math.PI / 180);
          const strength = Math.max(0.2, Math.min(1, numberValue(signal.strength, 0) / 100));
          const radius = 130 + strength * 245;
          const x = center.x + Math.cos(angle) * radius;
          const y = center.y + Math.sin(angle) * radius;
          const reveal = clamp01(interpolate(frame, [24 + index * 10, 42 + index * 10], [0, 1], { extrapolateRight: "clamp" }));
          const color = index % 3 === 0 ? palette.green : index % 3 === 1 ? palette.cyan : palette.amber;
          return (
            <g key={`${signal.label}-${index}`} opacity={reveal}>
              <circle cx={x} cy={y} r={18 + strength * 16} fill={`${color}cc`} stroke="rgba(255,255,255,0.72)" strokeWidth="3" />
              <foreignObject x={x + 30} y={y - 36} width="280" height="92">
                <div style={{ color: palette.text, fontSize: 27, lineHeight: 0.98, fontWeight: 900, letterSpacing: "-0.03em" }}>{signal.label}</div>
                {signal.detail && <div style={{ marginTop: 6, color: palette.muted, fontSize: 18, lineHeight: 1.05, fontWeight: 720 }}>{signal.detail}</div>}
              </foreignObject>
            </g>
          );
        })}
      </svg>
      <div style={{ position: "absolute", right: 106, top: 380, width: 560, padding: "36px 40px", borderRadius: 42, background: "rgba(8,15,25,0.88)", border: `1px solid ${palette.green}77`, boxShadow: "0 40px 130px rgba(0,0,0,0.46)" }}>
        <div style={{ fontSize: 70, lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.07em" }}>{scanLabel}</div>
      </div>
    </AbsoluteFill>
  );
};
