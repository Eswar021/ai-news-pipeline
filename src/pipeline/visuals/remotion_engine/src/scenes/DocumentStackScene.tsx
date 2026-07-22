import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { EditorialCanvas } from "./EditorialCanvas";
import { VisualSceneSpec } from "./types";
import { clamp01, editorialStyle, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

type DocumentItem = { title?: string; source?: string; date?: string; document_type?: string };

const docsFromPayload = (value: unknown): DocumentItem[] => {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      title: textValue(item.title) || textValue(item.label),
      source: textValue(item.source) || textValue(item.publisher),
      date: textValue(item.date),
      document_type: textValue(item.document_type),
    }))
    .filter((item) => item.title || item.source)
    .slice(0, 5);
};

export const DocumentStackScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const colors = editorialStyle(spec.visual_style);
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "SOURCE FILES");
  const docs = docsFromPayload(payload.documents);
  const focus = textValue(payload.focus_document_label);
  const enter = spring({ fps, frame, config: { damping: 19, stiffness: 100, mass: 0.8 } });

  return (
    <EditorialCanvas spec={spec} accentPosition="left">
      <div style={{ position: "absolute", left: 104, top: 100, width: 700 }}>
        {eyebrow && <div style={{ color: colors.accent, fontSize: 22, fontWeight: 850, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
        <div style={{ marginTop: eyebrow ? 20 : 0, fontFamily: colors.editorialFont, fontSize: readableTitleSize(headline, 82), lineHeight: 0.92, fontWeight: 700, letterSpacing: "-0.05em" }}>{headline}</div>
        {textValue(payload.stack_summary) && <div style={{ marginTop: 34, maxWidth: 610, paddingLeft: 24, borderLeft: `7px solid ${colors.accent}`, color: colors.muted, fontSize: 30, lineHeight: 1.16 }}>{shortDisplayText(textValue(payload.stack_summary), 110)}</div>}
      </div>

      <div style={{ position: "absolute", right: 118, top: 128, width: 930, height: 820, opacity: clamp01(enter) }}>
        {docs.map((doc, index) => {
          const active = doc.title === focus || (!focus && index === docs.length - 1);
          const reveal = clamp01(interpolate(frame, [10 + index * 11, 28 + index * 11], [0, 1], { extrapolateRight: "clamp" }));
          const left = active ? 180 : 80 + index * 36;
          const top = active ? 220 : 56 + index * 58;
          const rotate = active ? 0 : -6 + index * 2.4;
          return (
            <div key={`${doc.title}-${index}`} style={{ position: "absolute", left, top, zIndex: active ? 20 : index + 1, width: active ? 650 : 590, minHeight: active ? 350 : 285, padding: active ? "46px 50px" : "34px 38px", background: active ? "#fffdfa" : "#eee7dc", border: `1px solid ${active ? colors.accent : colors.text}35`, borderTop: `8px solid ${active ? colors.accent : colors.muted}`, boxShadow: active ? "0 32px 90px rgba(45,34,22,0.2)" : "0 18px 45px rgba(45,34,22,0.12)", opacity: reveal, transform: `rotate(${rotate}deg) translateY(${interpolate(reveal, [0, 1], [70, 0])}px) scale(${active ? interpolate(enter, [0, 1], [0.98, 1]) : 1})` }}>
              {doc.document_type && <div style={{ color: active ? colors.accent : colors.muted, fontSize: 19, fontWeight: 850, letterSpacing: "0.16em", textTransform: "uppercase" }}>{doc.document_type}</div>}
              <div style={{ marginTop: doc.document_type ? 20 : 0, fontFamily: colors.editorialFont, color: colors.text, fontSize: active ? 48 : 36, lineHeight: 0.96, fontWeight: 700, letterSpacing: "-0.04em" }}>{shortDisplayText(doc.title || "", active ? 74 : 62)}</div>
              <div style={{ marginTop: 22, color: colors.muted, fontSize: 23, lineHeight: 1.1, fontWeight: 680 }}>{doc.source}{doc.date ? `  /  ${doc.date}` : ""}</div>
              <div style={{ marginTop: 30, width: active ? "80%" : "72%", height: 5, background: active ? colors.accent : `${colors.muted}55` }} />
            </div>
          );
        })}
      </div>
    </EditorialCanvas>
  );
};
