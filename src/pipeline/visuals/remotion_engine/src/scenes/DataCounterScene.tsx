import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type Metric = {
  label?: string;
  value?: string;
  unit?: string;
  context?: string;
};

const metricList = (value: unknown): Metric[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      label: textValue(item.label),
      value: textValue(item.value),
      unit: textValue(item.unit),
      context: textValue(item.context),
    }))
    .filter((item) => item.value || item.label);
};

export const DataCounterScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || "The scale signal";
  const metrics = metricList(payload.metrics).slice(0, 3);
  const emphasis = textValue(payload.emphasis_label);
  const motif = textValue(payload.background_motif) || "newsroom_grid";
  const eyebrow = sceneEyebrow(payload, "DATA SIGNAL");
  const p = spring({ fps, frame, config: { damping: 16, stiffness: 110, mass: 0.75 } });
  const count = Math.max(1, metrics.length || 1);

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={motif} />
      {eyebrow && (
        <div style={{ position: "absolute", left: 94, top: 76, color: palette.green, fontSize: 24, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>
      )}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 126 : 96, fontSize: readableTitleSize(headline, 82), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>
        {headline}
      </div>
      <div style={{ position: "absolute", left: count === 1 ? 360 : 112, right: count === 1 ? 360 : 112, top: 300, display: "grid", gridTemplateColumns: `repeat(${count}, 1fr)`, gap: 30 }}>
        {(metrics.length ? metrics : [{ label: "Scale", value: "AI", context: spec.scene.script_excerpt || "momentum" }]).map((metric, index) => {
          const start = 14 + index * 14;
          const opacity = clamp01(interpolate(frame, [start, start + 16], [0, 1], { extrapolateRight: "clamp" }));
          const bar = clamp01(interpolate(frame, [start + 8, start + 42], [0.08, 1], { extrapolateRight: "clamp" }));
          return (
            <div key={`${metric.label}-${index}`} style={{ opacity, transform: `translateY(${interpolate(opacity, [0, 1], [44, 0])}px) scale(${interpolate(p, [0, 1], [0.97, 1])})`, minHeight: 330, borderRadius: 40, padding: "38px 38px 34px", background: "rgba(255,255,255,0.084)", border: "1px solid rgba(255,255,255,0.16)", boxShadow: "0 34px 110px rgba(0,0,0,0.34)" }}>
              <div style={{ color: index % 2 === 0 ? palette.cyan : palette.amber, fontSize: 29, fontWeight: 900, letterSpacing: "0.08em", textTransform: "uppercase" }}>{metric.label || "Metric"}</div>
              <div style={{ marginTop: 22, display: "flex", alignItems: "flex-end", gap: 12 }}>
                <div style={{ fontSize: count === 3 ? 98 : 118, lineHeight: 0.85, fontWeight: 950, letterSpacing: "-0.08em" }}>{metric.value || "AI"}</div>
                {metric.unit && <div style={{ color: palette.muted, fontSize: 34, fontWeight: 850 }}>{metric.unit}</div>}
              </div>
              <div style={{ marginTop: 24, height: 10, borderRadius: 999, background: "rgba(255,255,255,0.12)", overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${bar * 100}%`, borderRadius: 999, background: `linear-gradient(90deg, ${palette.cyan}, ${palette.green}, ${palette.amber})` }} />
              </div>
              <div style={{ marginTop: 24, color: "#d4e2f2", fontSize: 27, lineHeight: 1.1, fontWeight: 740 }}>{metric.context || "scale is becoming the story"}</div>
            </div>
          );
        })}
      </div>
      {emphasis && payload.show_emphasis_label !== false && (
        <div style={{ position: "absolute", left: 112, bottom: 78, padding: "18px 26px", borderRadius: 999, background: `${palette.cyan}1f`, border: `1px solid ${palette.cyan}66`, color: palette.cyan, fontSize: 30, fontWeight: 900 }}>
          {emphasis}
        </div>
      )}
    </AbsoluteFill>
  );
};
