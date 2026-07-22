import React from "react";
import { Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { EditorialCanvas } from "./EditorialCanvas";
import { VisualSceneSpec } from "./types";
import { clamp01, editorialStyle, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

type WalkthroughStep = { label?: string; detail?: string; target_text?: string };

const stepsFromPayload = (value: unknown): WalkthroughStep[] => {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      label: textValue(item.label),
      detail: textValue(item.detail),
      target_text: textValue(item.target_text),
    }))
    .filter((item) => item.label || item.detail || item.target_text)
    .slice(0, 4);
};

export const BrowserWalkthroughScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const asset = spec.scene.resolved_asset || {};
  const colors = editorialStyle(spec.visual_style);
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "GUIDED SOURCE");
  const url = textValue(payload.url);
  const host = url.replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  const steps = stepsFromPayload(payload.walkthrough_steps);
  const image = asset.asset_data_uri || "";
  const progress = clamp01(interpolate(frame, [12, Math.max(30, durationInFrames - 12)], [0, 1], { extrapolateRight: "clamp" }));
  const activeIndex = Math.min(Math.max(steps.length - 1, 0), Math.floor(progress * Math.max(steps.length, 1)));

  return (
    <EditorialCanvas spec={spec} accentPosition="right">
      <div style={{ position: "absolute", left: 100, top: 92, width: 600 }}>
        {eyebrow && <div style={{ color: colors.accent, fontSize: 22, fontWeight: 850, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
        <div style={{ marginTop: eyebrow ? 20 : 0, fontFamily: colors.editorialFont, fontSize: readableTitleSize(headline, 76), lineHeight: 0.92, fontWeight: 700, letterSpacing: "-0.05em" }}>{headline}</div>
      </div>

      <div style={{ position: "absolute", left: 104, bottom: 100, width: 540, display: "flex", flexDirection: "column", gap: 20 }}>
        {steps.map((step, index) => {
          const active = index === activeIndex;
          const reveal = clamp01(interpolate(frame, [12 + index * 10, 28 + index * 10], [0, 1], { extrapolateRight: "clamp" }));
          return (
            <div key={`${step.label}-${index}`} style={{ display: "grid", gridTemplateColumns: "42px 1fr", gap: 18, opacity: reveal, transform: `translateX(${interpolate(reveal, [0, 1], [-24, 0])}px)` }}>
              <div style={{ color: active ? colors.accent : colors.muted, fontSize: 24, fontWeight: 850 }}>{String(index + 1).padStart(2, "0")}</div>
              <div style={{ paddingBottom: 16, borderBottom: `1px solid ${active ? colors.accent : colors.text}30` }}>
                <div style={{ color: active ? colors.text : colors.muted, fontSize: 29, lineHeight: 1, fontWeight: 760 }}>{shortDisplayText(step.label || step.target_text || "", 46)}</div>
                {step.detail && <div style={{ marginTop: 8, color: colors.muted, fontSize: 21, lineHeight: 1.12 }}>{shortDisplayText(step.detail, 72)}</div>}
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ position: "absolute", right: 88, top: 92, width: 1110, height: 860, overflow: "hidden", background: "#fffdfa", border: `1px solid ${colors.text}30`, boxShadow: "0 30px 90px rgba(45,34,22,0.16)" }}>
        <div style={{ height: 54, display: "flex", alignItems: "center", padding: "0 24px", background: "#e9e1d5", borderBottom: `1px solid ${colors.text}22`, color: colors.muted, fontSize: 19, fontWeight: 700 }}>{host}</div>
        {image ? (
          <Img src={image} style={{ width: "100%", height: "calc(100% - 54px)", objectFit: "cover", objectPosition: `center ${22 + progress * 52}%`, transform: `scale(${1.02 + progress * 0.06})` }} />
        ) : (
          <div style={{ height: "calc(100% - 54px)", display: "flex", alignItems: "center", justifyContent: "center", color: colors.muted, fontSize: 32 }}>Source capture unavailable</div>
        )}
        <div style={{ position: "absolute", right: 26, top: 88 + activeIndex * 120, width: 280, padding: "14px 18px", background: "rgba(255,253,250,0.94)", borderLeft: `7px solid ${colors.accent}`, color: colors.text, fontSize: 23, lineHeight: 1.08, fontWeight: 720 }}>
          {shortDisplayText(steps[activeIndex]?.target_text || steps[activeIndex]?.label || textValue(payload.focus_text), 74)}
        </div>
      </div>
    </EditorialCanvas>
  );
};
