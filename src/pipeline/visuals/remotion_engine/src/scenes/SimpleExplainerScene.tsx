import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { EditorialCanvas } from "./EditorialCanvas";
import { VisualSceneSpec } from "./types";
import { clamp01, editorialStyle, textValue } from "./style";

type ExplainerItem = { label: string; detail: string };

const explainerItems = (value: unknown): ExplainerItem[] => {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    .map((item) => ({ label: textValue(item.label), detail: textValue(item.detail) }))
    .filter((item) => item.label)
    .slice(0, 4);
};

export const SimpleExplainerScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const colors = editorialStyle(spec.visual_style);
  const headline = textValue(payload.headline);
  const items = explainerItems(payload.items);
  const focus = textValue(payload.focus_item_label).toLowerCase();
  const connector = textValue(payload.connector_label);
  const orientation = textValue(payload.orientation) || "horizontal";
  const enter = spring({ fps, frame, config: { damping: 22, stiffness: 90, mass: 0.9 } });
  const horizontal = orientation !== "vertical";

  return (
    <EditorialCanvas spec={spec} accentPosition="left">
      <div style={{ position: "absolute", left: 132, right: 132, top: 86 }}>
        <div
          style={{
            maxWidth: 1450,
            fontFamily: colors.editorialFont,
            fontSize: headline.length > 70 ? 66 : 78,
            lineHeight: 0.98,
            fontWeight: 700,
            letterSpacing: "-0.04em",
          }}
        >
          {headline}
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: horizontal ? 128 : 410,
          right: horizontal ? 128 : 410,
          top: horizontal ? 390 : 260,
          bottom: horizontal ? 180 : 120,
          display: "flex",
          flexDirection: horizontal ? "row" : "column",
          alignItems: "stretch",
          justifyContent: "center",
          gap: horizontal ? 46 : 24,
          opacity: clamp01(enter),
        }}
      >
        {items.map((item, index) => {
          const reveal = clamp01(interpolate(frame, [12 + index * 10, 28 + index * 10], [0, 1], { extrapolateRight: "clamp" }));
          const active = focus ? item.label.toLowerCase() === focus : index === items.length - 1;
          return (
            <React.Fragment key={`${item.label}-${index}`}>
              <div
                style={{
                  position: "relative",
                  flex: horizontal ? 1 : undefined,
                  minHeight: horizontal ? 290 : 118,
                  display: "flex",
                  flexDirection: horizontal ? "column" : "row",
                  alignItems: horizontal ? "center" : "center",
                  justifyContent: "center",
                  textAlign: horizontal ? "center" : "left",
                  gap: horizontal ? 22 : 34,
                  opacity: reveal,
                  transform: `translate${horizontal ? "Y" : "X"}(${(1 - reveal) * 26}px)`,
                }}
              >
                <div
                  style={{
                    width: horizontal ? 112 : 78,
                    height: horizontal ? 112 : 78,
                    flex: "0 0 auto",
                    borderRadius: "50%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    border: `3px solid ${active ? colors.accent : `${colors.text}42`}`,
                    color: active ? colors.background : colors.text,
                    background: active ? colors.accent : `${colors.background}cc`,
                    fontSize: horizontal ? 42 : 30,
                    fontWeight: 800,
                  }}
                >
                  {index + 1}
                </div>
                <div style={{ maxWidth: horizontal ? 330 : 900 }}>
                  <div style={{ fontSize: horizontal ? 40 : 36, lineHeight: 1.02, fontWeight: 800 }}>{item.label}</div>
                  {item.detail && (
                    <div style={{ marginTop: 12, color: colors.muted, fontSize: horizontal ? 27 : 25, lineHeight: 1.18, fontWeight: 550 }}>
                      {item.detail}
                    </div>
                  )}
                </div>
              </div>
              {index < items.length - 1 && horizontal && (
                <div style={{ alignSelf: "center", width: 54, height: 2, background: `${colors.text}35`, position: "relative" }}>
                  <div style={{ position: "absolute", right: -1, top: -6, width: 12, height: 12, borderTop: `2px solid ${colors.accent}`, borderRight: `2px solid ${colors.accent}`, transform: "rotate(45deg)" }} />
                  {connector && index === 0 && (
                    <div style={{ position: "absolute", width: 150, left: -50, top: -38, textAlign: "center", color: colors.muted, fontSize: 20, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {connector}
                    </div>
                  )}
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </EditorialCanvas>
  );
};

