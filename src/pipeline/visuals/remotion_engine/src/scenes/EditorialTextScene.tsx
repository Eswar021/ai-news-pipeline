import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { EditorialCanvas } from "./EditorialCanvas";
import { VisualSceneSpec } from "./types";
import { clamp01, editorialStyle, listValue, textValue } from "./style";

const normalized = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");

export const EditorialTextScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const colors = editorialStyle(spec.visual_style);
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const eyebrow = textValue(payload.eyebrow);
  const supporting = textValue(payload.supporting_text);
  const accents = new Set(listValue(payload.accent_words).map(normalized));
  const words = headline.split(/\s+/).filter(Boolean);
  const entrance = spring({ fps, frame, config: { damping: 20, stiffness: 82, mass: 0.9 } });
  const composition = textValue(payload.composition) || "editorial_center";
  const centered = composition === "editorial_center";
  const headlineSize = headline.length > 86 ? 86 : headline.length > 58 ? 102 : headline.length > 34 ? 120 : 142;

  return (
    <EditorialCanvas spec={spec} accentPosition={centered ? "center" : "right"}>
      <div
        style={{
          position: "absolute",
          left: centered ? 220 : 150,
          right: centered ? 220 : composition === "editorial_split" ? 650 : 320,
          top: 155,
          bottom: 120,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: centered ? "center" : "flex-start",
          textAlign: centered ? "center" : "left",
          transform: `translateY(${interpolate(entrance, [0, 1], [34, 0])}px)`,
          opacity: clamp01(entrance),
        }}
      >
        {eyebrow && (
          <div
            style={{
              color: colors.accent,
              fontFamily: colors.sansFont,
              fontSize: 27,
              fontWeight: 800,
              letterSpacing: "0.19em",
              textTransform: "uppercase",
              marginBottom: 30,
            }}
          >
            {eyebrow}
          </div>
        )}
        <div
          style={{
            fontFamily: colors.editorialFont,
            fontSize: headlineSize,
            lineHeight: 0.91,
            fontWeight: 700,
            letterSpacing: "-0.052em",
            maxWidth: 1500,
          }}
        >
          {words.map((word, index) => {
            const reveal = clamp01(interpolate(frame, [8 + index * 2.2, 19 + index * 2.2], [0, 1], { extrapolateRight: "clamp" }));
            const accented = accents.has(normalized(word));
            return (
              <span
                key={`${word}-${index}`}
                style={{
                  display: "inline-block",
                  color: accented ? colors.accent : colors.text,
                  opacity: reveal,
                  transform: `translateY(${(1 - reveal) * 20}px)`,
                  marginRight: "0.22em",
                }}
              >
                {word}
              </span>
            );
          })}
        </div>
        {supporting && (
          <div
            style={{
              marginTop: 42,
              maxWidth: 1050,
              color: colors.muted,
              fontSize: supporting.length > 82 ? 31 : 37,
              lineHeight: 1.22,
              fontWeight: 550,
              opacity: clamp01(interpolate(frame, [24, 42], [0, 1], { extrapolateRight: "clamp" })),
            }}
          >
            {supporting}
          </div>
        )}
      </div>
    </EditorialCanvas>
  );
};

