import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type StepItem = { label?: string; detail?: string };

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const stepsFromPayload = (value: unknown): StepItem[] => {
  const items = objectList<Record<string, unknown>>(value)
    .map((item) => ({
      label: textValue(item.label) || textValue(item.name),
      detail: textValue(item.detail) || textValue(item.description),
    }))
    .filter((item) => item.label);
  return items.slice(0, 6);
};

export const ProcessZoomScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || "Zoom into the workflow";
  const eyebrow = sceneEyebrow(payload, "PROCESS ZOOM");
  const steps = stepsFromPayload(payload.steps).length
    ? stepsFromPayload(payload.steps)
    : [
        { label: "Input", detail: "user task" },
        { label: "Reasoning", detail: "plan the work" },
        { label: "Tool call", detail: "execute action" },
        { label: "Result", detail: "return output" },
      ];
  const focusLabel = textValue(payload.focus_step_label) || steps[Math.min(1, steps.length - 1)]?.label || "Focus";
  const focusIndex = Math.max(0, steps.findIndex((step) => step.label === focusLabel));
  const focus = steps[focusIndex] || steps[0];
  const zoomNote = textValue(payload.zoom_note) || focus.detail || "the step that changes the outcome";
  const p = spring({ fps, frame, config: { damping: 18, stiffness: 112, mass: 0.72 } });

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "newsroom_grid"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.amber, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 122 : 92, fontSize: readableTitleSize(headline, 84), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>

      <div style={{ position: "absolute", left: 96, top: 300, bottom: 100, width: 560, display: "flex", flexDirection: "column", gap: 18 }}>
        {steps.map((step, index) => {
          const reveal = clamp01(interpolate(frame, [14 + index * 9, 28 + index * 9], [0, 1], { extrapolateRight: "clamp" }));
          const active = index === focusIndex;
          return (
            <div key={`${step.label}-${index}`} style={{ opacity: reveal, transform: `translateX(${interpolate(reveal, [0, 1], [-34, 0])}px)`, display: "grid", gridTemplateColumns: "64px 1fr", gap: 18, alignItems: "center", padding: "18px 20px", borderRadius: 28, background: active ? `${palette.cyan}20` : "rgba(255,255,255,0.075)", border: `1px solid ${active ? palette.cyan : "rgba(255,255,255,0.14)"}` }}>
              <div style={{ width: 58, height: 58, borderRadius: 20, display: "flex", alignItems: "center", justifyContent: "center", color: "#061016", background: active ? palette.cyan : index % 2 === 0 ? palette.amber : palette.green, fontSize: 26, fontWeight: 950 }}>{index + 1}</div>
              <div>
                <div style={{ fontSize: 31, lineHeight: 0.98, fontWeight: 900, letterSpacing: "-0.035em" }}>{step.label}</div>
                {step.detail && <div style={{ marginTop: 6, color: "#d5e3f3", fontSize: 20, lineHeight: 1.06, fontWeight: 720 }}>{step.detail}</div>}
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ position: "absolute", right: 112, top: 282, width: 1040, height: 610, borderRadius: 58, padding: "58px 64px", background: "linear-gradient(135deg, rgba(99,215,255,0.22), rgba(255,255,255,0.075))", border: `2px solid ${palette.cyan}88`, boxShadow: `0 46px 150px rgba(0,0,0,0.48), 0 0 90px ${palette.cyan}28`, opacity: clamp01(p), transform: `translateY(${interpolate(p, [0, 1], [54, 0])}px) scale(${interpolate(p, [0, 1], [0.965, 1])})` }}>
        <div style={{ color: palette.cyan, fontSize: 27, fontWeight: 950, letterSpacing: "0.12em", textTransform: "uppercase" }}>Active step</div>
        <div style={{ marginTop: 26, fontSize: 102, lineHeight: 0.86, fontWeight: 950, letterSpacing: "-0.08em" }}>{focus.label}</div>
        <div style={{ marginTop: 34, color: "#dce8f6", fontSize: 43, lineHeight: 1.04, fontWeight: 780, letterSpacing: "-0.04em", maxWidth: 820 }}>{zoomNote}</div>
        <div style={{ position: "absolute", right: 58, bottom: 52, width: 180, height: 180, borderRadius: 999, border: `3px solid ${palette.cyan}55`, boxShadow: `0 0 70px ${palette.cyan}33`, transform: `scale(${1 + Math.sin(frame / 8) * 0.035})` }} />
      </div>
    </AbsoluteFill>
  );
};
