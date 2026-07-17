import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type TimelineEvent = {
  label?: string;
  time?: string;
  detail?: string;
};

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const eventsFromPayload = (value: unknown): TimelineEvent[] => {
  const items = objectList<Record<string, unknown>>(value)
    .map((item) => ({
      label: textValue(item.label) || textValue(item.title),
      time: textValue(item.time) || textValue(item.date),
      detail: textValue(item.detail) || textValue(item.description),
    }))
    .filter((item) => item.label || item.detail || item.time);
  if (items.length) {
    return items.slice(0, 5);
  }
  return [];
};

export const TimelineZoomScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "TIMELINE ZOOM");
  const events = eventsFromPayload(payload.events);
  const focusLabel = textValue(payload.focus_event_label);
  const focusIndex = Math.max(0, events.findIndex((event) => event.label === focusLabel || event.time === focusLabel));
  const focus = events[focusIndex] || events[events.length - 1];
  const p = spring({ fps, frame, config: { damping: 18, stiffness: 112, mass: 0.72 } });

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "newsroom_grid"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.amber, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 122 : 92, fontSize: readableTitleSize(headline, 84), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>

      <svg viewBox="0 0 1920 650" style={{ position: "absolute", left: 0, top: 286, width: 1920, height: 650 }}>
        <line x1="190" y1="314" x2="1730" y2="314" stroke="rgba(255,255,255,0.14)" strokeWidth="10" strokeLinecap="round" />
        <line x1="190" y1="314" x2={190 + 1540 * clamp01(interpolate(frame, [18, 78], [0, 1], { extrapolateRight: "clamp" }))} y2="314" stroke={palette.cyan} strokeWidth="10" strokeLinecap="round" />
        {events.map((event, index) => {
          const x = 230 + index * (1460 / Math.max(1, events.length - 1));
          const reveal = clamp01(interpolate(frame, [22 + index * 10, 40 + index * 10], [0, 1], { extrapolateRight: "clamp" }));
          const isFocus = index === focusIndex;
          const color = isFocus ? palette.amber : index % 2 === 0 ? palette.cyan : palette.green;
          return (
            <g key={`${event.label}-${index}`} opacity={reveal}>
              <circle cx={x} cy="314" r={isFocus ? 30 : 21} fill={color} stroke="rgba(255,255,255,0.75)" strokeWidth="4" />
              <foreignObject x={x - 160} y={index % 2 === 0 ? 70 : 380} width="320" height="190">
                <div style={{ textAlign: "center", padding: "18px 16px", borderRadius: 26, background: isFocus ? `${palette.amber}20` : "rgba(255,255,255,0.075)", border: `1px solid ${isFocus ? palette.amber : "rgba(255,255,255,0.13)"}` }}>
                  {event.time && <div style={{ color, fontSize: 21, fontWeight: 950, letterSpacing: "0.11em", textTransform: "uppercase" }}>{event.time}</div>}
                  <div style={{ marginTop: event.time ? 10 : 0, color: palette.text, fontSize: isFocus ? 32 : 26, lineHeight: 0.96, fontWeight: 920, letterSpacing: "-0.035em" }}>{event.label}</div>
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>

      <div style={{ position: "absolute", right: 108, bottom: 82, width: 660, padding: "38px 42px", borderRadius: 42, background: "rgba(8,15,25,0.93)", border: `2px solid ${palette.amber}88`, boxShadow: "0 42px 140px rgba(0,0,0,0.54)", opacity: clamp01(p), transform: `translateY(${interpolate(p, [0, 1], [52, 0])}px)` }}>
        <div style={{ fontSize: 58, lineHeight: 0.92, fontWeight: 950, letterSpacing: "-0.06em" }}>{focus.label || focus.time}</div>
        {focus.detail && <div style={{ marginTop: 22, color: "#d9e6f4", fontSize: 27, lineHeight: 1.12, fontWeight: 740 }}>{focus.detail}</div>}
      </div>
    </AbsoluteFill>
  );
};
