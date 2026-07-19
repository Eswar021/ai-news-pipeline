import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type DocumentItem = {
  title?: string;
  source?: string;
  date?: string;
  document_type?: string;
};

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const docsFromPayload = (value: unknown): DocumentItem[] => {
  const docs = objectList<Record<string, unknown>>(value)
    .map((item) => ({
      title: textValue(item.title) || textValue(item.label),
      source: textValue(item.source) || textValue(item.publisher),
      date: textValue(item.date) || textValue(item.published_at),
      document_type: textValue(item.document_type) || textValue(item.type),
    }))
    .filter((item) => item.title || item.source);
  if (docs.length) {
    return docs.slice(0, 6);
  }
  return [];
};

export const DocumentStackScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "DOCUMENT STACK");
  const docs = docsFromPayload(payload.documents);
  const focus = textValue(payload.focus_document_label);
  const p = spring({ fps, frame, config: { damping: 18, stiffness: 105, mass: 0.72 } });

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "newsroom_grid"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.green, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, top: eyebrow ? 122 : 92, width: 760, fontSize: readableTitleSize(headline, 82), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>

      <div style={{ position: "absolute", right: 130, top: 188, width: 820, height: 760 }}>
        {docs.map((doc, index) => {
          const reveal = clamp01(interpolate(frame, [12 + index * 10, 30 + index * 10], [0, 1], { extrapolateRight: "clamp" }));
          const active = doc.title === focus;
          const rotate = -7 + index * 3;
          const y = 76 + index * 66;
          const x = 90 - index * 16;
          const color = active ? palette.cyan : index % 2 === 0 ? palette.amber : palette.green;
          return (
            <div key={`${doc.title}-${index}`} style={{ position: "absolute", left: active ? 72 : x, top: active ? 190 : y, zIndex: active ? 12 : index + 1, width: 620, minHeight: 280, padding: "34px 38px", borderRadius: 34, background: active ? "rgba(255,255,255,0.95)" : "rgba(229,238,247,0.88)", border: `3px solid ${active ? color : "rgba(255,255,255,0.6)"}`, color: "#071018", boxShadow: active ? `0 40px 120px ${palette.cyan}28` : "0 26px 80px rgba(0,0,0,0.26)", opacity: reveal, transform: `rotate(${active ? 0 : rotate}deg) translateY(${interpolate(reveal, [0, 1], [90, 0])}px) scale(${active ? interpolate(p, [0, 1], [0.98, 1.02]) : 1})`, transformOrigin: "center center" }}>
              {doc.document_type && <div style={{ color, fontSize: 23, fontWeight: 950, letterSpacing: "0.13em", textTransform: "uppercase" }}>{doc.document_type}</div>}
              <div style={{ marginTop: doc.document_type ? 20 : 0, fontSize: active ? 45 : 36, lineHeight: 0.95, fontWeight: 950, letterSpacing: "-0.055em" }}>{doc.title}</div>
              <div style={{ marginTop: 18, color: "#33485f", fontSize: 25, lineHeight: 1.08, fontWeight: 780 }}>{doc.source}{doc.date ? ` - ${doc.date}` : ""}</div>
              <div style={{ marginTop: 26, height: 10, width: "78%", borderRadius: 999, background: `${color}aa` }} />
              <div style={{ marginTop: 14, height: 10, width: "58%", borderRadius: 999, background: "rgba(7,16,24,0.18)" }} />
            </div>
          );
        })}
      </div>

      {textValue(payload.stack_summary) && <div style={{ position: "absolute", left: 104, bottom: 92, width: 650, padding: "28px 32px", borderRadius: 36, background: "rgba(8,15,25,0.88)", border: `1px solid ${palette.green}77`, color: "#e3edf8", fontSize: 36, lineHeight: 1.02, fontWeight: 870, letterSpacing: "-0.04em" }}>{textValue(payload.stack_summary)}</div>}
    </AbsoluteFill>
  );
};
