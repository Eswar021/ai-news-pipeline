import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, listValue, palette, readableTitleSize, sceneEyebrow, textValue } from "./style";

type MatrixRow = {
  label?: string;
  values?: string[];
  highlight?: string;
};

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const rowsFromPayload = (value: unknown, columns: string[]): MatrixRow[] => {
  const objects = objectList<Record<string, unknown>>(value)
    .map((item) => {
      const values = Array.isArray(item.values)
        ? item.values.map(String)
        : columns.map((column) => textValue(item[column]) || textValue(item[column.toLowerCase()]));
      return {
        label: textValue(item.label) || textValue(item.name),
        values: values.filter(Boolean),
        highlight: textValue(item.highlight) || textValue(item.best),
      };
    })
    .filter((item) => item.label || item.values.length);
  return objects.slice(0, 5);
};

export const CapabilityMatrixScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const eyebrow = sceneEyebrow(payload, "CAPABILITY MATRIX");
  const columns = listValue(payload.columns).slice(0, 4);
  const rows = rowsFromPayload(payload.rows, columns).slice(0, 5);
  const highlightCell = textValue(payload.highlight_cell);

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "device_glow"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.green, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 122 : 92, fontSize: readableTitleSize(headline, 82), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>
      <div style={{ position: "absolute", left: 110, right: 110, top: 300, borderRadius: 44, padding: 26, background: "rgba(255,255,255,0.075)", border: "1px solid rgba(255,255,255,0.15)", boxShadow: "0 36px 130px rgba(0,0,0,0.40)" }}>
        <div style={{ display: "grid", gridTemplateColumns: `310px repeat(${columns.length}, 1fr)`, gap: 14, marginBottom: 14 }}>
          <div />
          {columns.map((column, index) => {
            const reveal = clamp01(interpolate(frame, [12 + index * 7, 26 + index * 7], [0, 1], { extrapolateRight: "clamp" }));
            return <div key={column} style={{ opacity: reveal, color: index % 2 === 0 ? palette.cyan : palette.amber, fontSize: 25, fontWeight: 950, textTransform: "uppercase", letterSpacing: "0.11em", textAlign: "center" }}>{column}</div>;
          })}
        </div>
        {rows.map((row, rowIndex) => {
          const reveal = clamp01(interpolate(frame, [24 + rowIndex * 11, 42 + rowIndex * 11], [0, 1], { extrapolateRight: "clamp" }));
          return (
            <div key={`${row.label}-${rowIndex}`} style={{ opacity: reveal, transform: `translateY(${interpolate(reveal, [0, 1], [26, 0])}px)`, display: "grid", gridTemplateColumns: `310px repeat(${columns.length}, 1fr)`, gap: 14, marginTop: 14 }}>
              <div style={{ minHeight: 96, borderRadius: 26, padding: "22px 24px", background: "rgba(8,15,25,0.82)", border: "1px solid rgba(255,255,255,0.12)", color: palette.text, fontSize: 31, lineHeight: 0.95, fontWeight: 950, letterSpacing: "-0.04em" }}>{row.label}</div>
              {columns.map((column, colIndex) => {
                const value = row.values?.[colIndex] || "";
                const isHighlight = Boolean(highlightCell && `${row.label} ${column} ${value}`.toLowerCase().includes(highlightCell.toLowerCase())) || row.highlight === column || row.highlight === value;
                const color = isHighlight ? palette.green : colIndex % 2 === 0 ? palette.cyan : palette.amber;
                return (
                  <div key={`${row.label}-${column}`} style={{ minHeight: 96, borderRadius: 26, padding: "20px 18px", display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", background: isHighlight ? `${palette.green}22` : "rgba(255,255,255,0.070)", border: `1px solid ${isHighlight ? palette.green : "rgba(255,255,255,0.11)"}`, color: isHighlight ? palette.text : "#d8e5f2", fontSize: 27, lineHeight: 1, fontWeight: 880, letterSpacing: "-0.025em", boxShadow: isHighlight ? `0 0 34px ${color}2d` : undefined }}>{value}</div>
                );
              })}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
