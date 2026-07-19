import React from "react";
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { VisualSceneSpec } from "./types";
import { editorialStyle, readableTitleSize, textValue } from "./style";

type DocumentPayload = {
  asset_id?: string;
  title?: string;
  source?: string;
};

const documentsFromPayload = (value: unknown): DocumentPayload[] =>
  Array.isArray(value)
    ? value.filter((item): item is DocumentPayload => Boolean(item) && typeof item === "object")
    : [];

export const SourceProofMontageScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const colors = editorialStyle(spec.visual_style);
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const focusLabel = textValue(payload.focus_document_label).toLowerCase();
  const documents = documentsFromPayload(payload.documents);
  const resolved = (spec.scene.resolved_asset?.assets || []).slice(0, 3);
  const progress = spring({ fps, frame, config: { damping: 20, stiffness: 92, mass: 0.82 } });

  return (
    <AbsoluteFill style={{ background: colors.background, color: colors.text, fontFamily: colors.sansFont, overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: 0.24, backgroundImage: "linear-gradient(rgba(23,22,17,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(23,22,17,0.025) 1px, transparent 1px)", backgroundSize: "72px 72px" }} />
      <div style={{ position: "absolute", left: 94, top: 76, width: 150, height: 8, background: colors.accent }} />
      <div style={{ position: "absolute", left: 94, top: 128, width: 610 }}>
        <div style={{ color: colors.accent, fontSize: 23, fontWeight: 900, letterSpacing: "0.17em", textTransform: "uppercase" }}>SOURCE PROOF</div>
        <div style={{ marginTop: 24, fontFamily: colors.editorialFont, fontSize: readableTitleSize(headline, 78), lineHeight: 0.91, fontWeight: 700, letterSpacing: "-0.052em" }}>{headline}</div>
        {textValue(payload.stack_summary) && (
          <div style={{ marginTop: 42, maxWidth: 540, paddingLeft: 22, borderLeft: `6px solid ${colors.accent}`, color: colors.muted, fontSize: 31, lineHeight: 1.08, fontWeight: 720 }}>{textValue(payload.stack_summary)}</div>
        )}
      </div>

      <div style={{ position: "absolute", left: 700, right: 70, top: 96, bottom: 70 }}>
        {resolved.map((asset, index) => {
          const document = documents.find((item) => textValue(item.asset_id) === textValue(asset.asset_id)) || documents[index] || {};
          const active = !focusLabel || textValue(document.title).toLowerCase() === focusLabel;
          const reveal = Math.max(0, Math.min(1, interpolate(frame, [8 + index * 11, 28 + index * 11], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })));
          const zoom = interpolate(frame, [0, durationInFrames], [1.035, active ? 1.0 : 1.015]);
          return (
            <div
              key={`${asset.asset_id}-${index}`}
              style={{
                position: "absolute",
                left: 68 + index * 105,
                top: 52 + index * 82,
                width: 860,
                height: 650,
                overflow: "hidden",
                borderRadius: 12,
                border: active ? `4px solid ${colors.accent}` : "1px solid rgba(23,22,17,0.22)",
                background: "#fffdfa",
                boxShadow: active ? "0 38px 110px rgba(42,35,25,0.28)" : "0 25px 70px rgba(42,35,25,0.2)",
                opacity: reveal,
                zIndex: active ? 8 : index + 1,
                transform: `translate(${interpolate(reveal, [0, 1], [90, 0])}px, ${interpolate(reveal, [0, 1], [60, 0])}px) rotate(${(index - 1) * 2.2}deg) scale(${active ? interpolate(progress, [0, 1], [0.985, 1]) : 1})`,
                transformOrigin: "center center",
              }}
            >
              <div style={{ height: 48, display: "flex", alignItems: "center", gap: 10, padding: "0 18px", background: "#e9e1d5", borderBottom: "1px solid rgba(23,22,17,0.16)", color: colors.muted, fontSize: 18, fontWeight: 760 }}>
                <span style={{ width: 12, height: 12, borderRadius: 99, background: "#ff5f57" }} />
                <span style={{ width: 12, height: 12, borderRadius: 99, background: "#ffbd2e" }} />
                <span style={{ width: 12, height: 12, borderRadius: 99, background: "#28c840" }} />
                <span style={{ marginLeft: 10 }}>{textValue(asset.domain) || textValue(document.source) || "SOURCE"}</span>
              </div>
              {asset.asset_data_uri ? (
                <Img src={asset.asset_data_uri} style={{ width: "100%", height: "calc(100% - 48px)", objectFit: "cover", objectPosition: "center 24%", transform: `scale(${zoom})` }} />
              ) : (
                <div style={{ height: "calc(100% - 48px)", display: "flex", alignItems: "center", justifyContent: "center", color: colors.muted, fontSize: 28, fontWeight: 800 }}>SOURCE CAPTURE UNAVAILABLE</div>
              )}
              <div style={{ position: "absolute", left: 20, right: 20, bottom: 18, padding: "12px 16px", color: "#fffaf2", background: "rgba(23,22,17,0.84)", borderLeft: `6px solid ${colors.accent}`, fontSize: 24, lineHeight: 1.04, fontWeight: 790 }}>{textValue(document.title) || textValue(document.source)}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
