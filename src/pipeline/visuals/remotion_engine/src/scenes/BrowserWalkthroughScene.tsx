import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, listValue, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type WalkthroughStep = {
  label?: string;
  detail?: string;
  target_text?: string;
};

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const stepsFromPayload = (value: unknown): WalkthroughStep[] => {
  const objects = objectList<Record<string, unknown>>(value)
    .map((item) => ({
      label: textValue(item.label) || textValue(item.title) || textValue(item.step),
      detail: textValue(item.detail) || textValue(item.description),
      target_text: textValue(item.target_text) || textValue(item.targetText),
    }))
    .filter((item) => item.label || item.detail || item.target_text);
  if (objects.length) {
    return objects.slice(0, 5);
  }
  const phrases = listValue(value);
  if (phrases.length) {
    return phrases.slice(0, 5).map((phrase) => ({ label: phrase }));
  }
  return [];
};

export const BrowserWalkthroughScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || textValue(payload.overlay_headline) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "BROWSER WALKTHROUGH");
  const url = textValue(payload.url);
  const host = url.replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  const focusText = textValue(payload.focus_text) || textValue(payload.target_text) || textValue(payload.overlay_headline);
  const pageTitle = textValue(payload.browser_title) || textValue(payload.page_title) || focusText;
  const steps = stepsFromPayload(payload.walkthrough_steps).slice(0, 5);
  const highlightPhrases = listValue(payload.highlight_phrases).slice(0, 3);
  const progress = clamp01(interpolate(frame, [18, Math.max(60, durationInFrames - 20)], [0, 1], { extrapolateRight: "clamp" }));
  const scrollY = interpolate(progress, [0, 1], [0, -245]);
  const scanX = interpolate(frame, [28, Math.max(82, durationInFrames - 16)], [-260, 1060], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "newsroom_grid"} />
      {eyebrow && <div style={{ position: "absolute", left: 92, top: 70, color: palette.cyan, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, top: eyebrow ? 120 : 88, width: 760, fontSize: readableTitleSize(headline, 78), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>

      <div style={{ position: "absolute", left: 92, bottom: 92, width: 610, display: "flex", flexDirection: "column", gap: 16 }}>
        {steps.slice(0, 3).map((step, index) => {
          const reveal = clamp01(interpolate(frame, [18 + index * 13, 34 + index * 13], [0, 1], { extrapolateRight: "clamp" }));
          return (
            <div key={`${step.label}-${index}`} style={{ opacity: reveal, transform: `translateX(${interpolate(reveal, [0, 1], [-28, 0])}px)`, padding: "18px 22px", borderRadius: 26, background: index === 1 ? `${palette.cyan}20` : "rgba(255,255,255,0.075)", border: `1px solid ${index === 1 ? palette.cyan : "rgba(255,255,255,0.13)"}` }}>
              <div style={{ color: index === 1 ? palette.cyan : palette.amber, fontSize: 22, fontWeight: 950, letterSpacing: "0.11em", textTransform: "uppercase" }}>{step.label || `Step ${index + 1}`}</div>
              {(step.detail || step.target_text) && <div style={{ marginTop: 8, color: "#e5eef8", fontSize: 30, lineHeight: 1.02, fontWeight: 830, letterSpacing: "-0.035em" }}>{step.detail || step.target_text}</div>}
            </div>
          );
        })}
      </div>

      <div style={{ position: "absolute", right: 96, top: 118, width: 1030, height: 780, borderRadius: 44, overflow: "hidden", background: "rgba(9,16,26,0.94)", border: "1px solid rgba(255,255,255,0.18)", boxShadow: "0 46px 150px rgba(0,0,0,0.55)" }}>
        <div style={{ height: 76, background: "rgba(255,255,255,0.08)", display: "flex", alignItems: "center", gap: 14, padding: "0 24px", borderBottom: "1px solid rgba(255,255,255,0.12)" }}>
          {[palette.red, palette.amber, palette.green].map((color) => <div key={color} style={{ width: 18, height: 18, borderRadius: 99, background: color }} />)}
          <div style={{ marginLeft: 16, flex: 1, height: 38, borderRadius: 999, background: "rgba(255,255,255,0.11)", display: "flex", alignItems: "center", padding: "0 20px", color: palette.muted, fontSize: 20, fontWeight: 760 }}>{host}</div>
        </div>
        <div style={{ position: "absolute", left: 0, right: 0, top: 76, bottom: 0, overflow: "hidden" }}>
          <div style={{ transform: `translateY(${scrollY}px)`, transition: "transform 120ms linear", padding: "44px 54px 160px" }}>
            <div style={{ width: 620, height: 36, borderRadius: 999, background: `${palette.cyan}60`, marginBottom: 24 }} />
            <div style={{ fontSize: readableTitleSize(pageTitle, 48), lineHeight: 0.96, fontWeight: 950, letterSpacing: "-0.055em", maxWidth: 780 }}>{pageTitle}</div>
            <div style={{ marginTop: 32, display: "grid", gridTemplateColumns: "1fr 280px", gap: 34 }}>
              <div>
                {steps.map((step, index) => (
                  <div key={`page-${index}`} style={{ marginTop: index === 0 ? 0 : 28, padding: 26, borderRadius: 28, background: index === 1 ? "rgba(99,215,255,0.13)" : "rgba(255,255,255,0.07)", border: `1px solid ${index === 1 ? `${palette.cyan}88` : "rgba(255,255,255,0.11)"}` }}>
                    <div style={{ color: index === 1 ? palette.cyan : palette.text, fontSize: 31, fontWeight: 910, letterSpacing: "-0.035em" }}>{step.label || `Section ${index + 1}`}</div>
                    <div style={{ marginTop: 12, color: "#d7e4f1", fontSize: 25, lineHeight: 1.16, fontWeight: 690 }}>{step.target_text || step.detail || focusText}</div>
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                {highlightPhrases.map((item, index) => (
                  <div key={`${item}-${index}`} style={{ height: 88, borderRadius: 24, background: "rgba(255,255,255,0.075)", border: "1px solid rgba(255,255,255,0.10)", padding: 20, color: index === 1 ? palette.amber : palette.muted, fontSize: 22, lineHeight: 1.05, fontWeight: 850 }}>{item}</div>
                ))}
              </div>
            </div>
          </div>
          <div style={{ position: "absolute", left: scanX, top: 92, width: 180, height: 620, background: "linear-gradient(90deg, transparent, rgba(255,207,112,0.22), transparent)", filter: "blur(4px)" }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
