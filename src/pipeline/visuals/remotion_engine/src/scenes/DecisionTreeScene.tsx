import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, listValue, palette, readableBodySize, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

type Branch = {
  label?: string;
  outcome?: string;
  risk?: string;
};

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const branchesFromPayload = (value: unknown): Branch[] => {
  const objects = objectList<Record<string, unknown>>(value)
    .map((item) => ({
      label: textValue(item.label) || textValue(item.choice),
      outcome: textValue(item.outcome) || textValue(item.result) || textValue(item.detail),
      risk: textValue(item.risk) || textValue(item.note),
    }))
    .filter((item) => item.label || item.outcome);
  if (objects.length) {
    return objects.slice(0, 4);
  }
  const items = listValue(value);
  if (items.length) {
    return items.slice(0, 4).map((item) => ({ label: item }));
  }
  return [];
};

export const DecisionTreeScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || spec.scene.script_excerpt || "";
  const rootLabel = textValue(payload.root_label);
  const selectedPath = textValue(payload.selected_path_label);
  const branches = branchesFromPayload(payload.branches);
  const eyebrow = sceneEyebrow(payload, "DECISION TREE");
  const p = spring({ fps, frame, config: { damping: 17, stiffness: 108, mass: 0.72 } });
  const coords = branches.length <= 3
    ? [
        { x: 430, y: 530 },
        { x: 960, y: 610 },
        { x: 1490, y: 530 },
      ]
    : [
        { x: 405, y: 490 },
        { x: 845, y: 635 },
        { x: 1275, y: 635 },
        { x: 1515, y: 490 },
      ];
  const rootY = 175;
  const cardWidth = branches.length <= 3 ? 470 : 410;
  const cardHeight = branches.length <= 3 ? 172 : 154;

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "abstract_ai"} />
      {eyebrow && <div style={{ position: "absolute", left: 96, top: 72, color: palette.amber, fontSize: 23, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 122 : 92, fontSize: readableTitleSize(headline, 84), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>

      <svg viewBox="0 0 1920 760" style={{ position: "absolute", left: 0, right: 0, top: 282, height: 740 }}>
        <g transform={`scale(${interpolate(p, [0, 1], [0.985, 1])})`} style={{ transformOrigin: "960px 380px" }}>
          <g transform={`translate(960 ${rootY})`}>
            <rect x="-260" y="-86" width="520" height="172" rx="44" fill={`${palette.cyan}24`} stroke={palette.cyan} strokeWidth="4" />
            <foreignObject x="-218" y="-48" width="436" height="96">
              <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: palette.text, textAlign: "center", fontSize: readableBodySize(rootLabel, 42), lineHeight: 0.96, fontWeight: 950, letterSpacing: "-0.045em" }}>
                {shortDisplayText(rootLabel, 36)}
              </div>
            </foreignObject>
          </g>
          {branches.map((branch, index) => {
            const pos = coords[index] || coords[0];
            const reveal = clamp01(interpolate(frame, [20 + index * 12, 40 + index * 12], [0, 1], { extrapolateRight: "clamp" }));
            const isSelected = branch.label === selectedPath || branch.outcome === selectedPath;
            const color = isSelected ? palette.green : index % 2 === 0 ? palette.cyan : palette.amber;
            const label = shortDisplayText(branch.label || "", 30);
            const outcome = shortDisplayText(branch.outcome || "", 54);
            const risk = shortDisplayText(branch.risk || "", 42);
            return (
              <g key={`${branch.label}-${index}`} opacity={reveal}>
                <path d={`M 960 ${rootY + 94} C 960 ${pos.y - 230}, ${pos.x} ${pos.y - 220}, ${pos.x} ${pos.y - cardHeight / 2 - 14}`} fill="none" stroke={color} strokeWidth={isSelected ? 9 : 5} strokeLinecap="round" opacity={isSelected ? 0.9 : 0.42} />
                <circle cx={960 + (pos.x - 960) * clamp01(interpolate(frame, [44 + index * 10, 84 + index * 10], [0, 1], { extrapolateRight: "clamp" }))} cy={rootY + 94 + (pos.y - cardHeight / 2 - 14 - (rootY + 94)) * clamp01(interpolate(frame, [44 + index * 10, 84 + index * 10], [0, 1], { extrapolateRight: "clamp" }))} r="10" fill={color} />
                <g transform={`translate(${pos.x} ${pos.y})`}>
                  <rect x={-cardWidth / 2} y={-cardHeight / 2} width={cardWidth} height={cardHeight} rx="38" fill={isSelected ? `${palette.green}25` : "rgba(255,255,255,0.09)"} stroke={isSelected ? palette.green : "rgba(255,255,255,0.20)"} strokeWidth={isSelected ? 4 : 2} />
                  <foreignObject x={-cardWidth / 2 + 36} y={-cardHeight / 2 + 26} width={cardWidth - 72} height={cardHeight - 52}>
                    <div style={{ height: "100%", display: "flex", flexDirection: "column", justifyContent: "center", textAlign: "center" }}>
                      <div style={{ color, fontSize: readableBodySize(label, 34), lineHeight: 0.95, fontWeight: 950, letterSpacing: "-0.04em" }}>{label}</div>
                      {outcome && <div style={{ marginTop: 14, color: "#dbe8f6", fontSize: readableBodySize(outcome, 25), lineHeight: 1.08, fontWeight: 780 }}>{outcome}</div>}
                      {risk && <div style={{ marginTop: 9, color: palette.muted, fontSize: 20, lineHeight: 1.05, fontWeight: 720 }}>{risk}</div>}
                    </div>
                  </foreignObject>
                </g>
              </g>
            );
          })}
        </g>
      </svg>
    </AbsoluteFill>
  );
};
