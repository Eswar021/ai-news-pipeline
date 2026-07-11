import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { MotionBackground } from "./Background";
import { VisualSceneSpec } from "./types";
import { clamp01, font, palette, readableBodySize, readableTitleSize, sceneEyebrow, shortDisplayText, textValue } from "./style";

type NodeItem = { id?: string; label?: string; role?: string };
type EdgeItem = { from?: string; to?: string; source?: string; target?: string; label?: string };

const objectList = <T extends Record<string, unknown>>(value: unknown): T[] =>
  Array.isArray(value) ? value.filter((item): item is T => Boolean(item) && typeof item === "object") : [];

const positionsFor = (count: number) => {
  const base = [
    { x: 960, y: 240 },
    { x: 430, y: 470 },
    { x: 1490, y: 470 },
    { x: 680, y: 660 },
    { x: 1240, y: 660 },
    { x: 960, y: 750 },
  ];
  if (count <= 4) {
    return [
      { x: 960, y: 260 },
      { x: 520, y: 570 },
      { x: 1400, y: 570 },
      { x: 960, y: 725 },
    ];
  }
  return base;
};

const nodeKey = (node: NodeItem) => `${node.id || node.label || ""}`.toLowerCase();

const nodeIndexFor = (nodes: NodeItem[], value: string) => {
  const needle = value.toLowerCase();
  const exact = nodes.findIndex((node) => nodeKey(node) === needle || `${node.label || ""}`.toLowerCase() === needle);
  return exact >= 0 ? exact : 0;
};

export const EcosystemMapScene: React.FC<{ spec: VisualSceneSpec }> = ({ spec }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const payload = spec.scene.payload || {};
  const headline = textValue(payload.headline) || "How the ecosystem connects";
  const nodes = objectList<NodeItem>(payload.nodes).slice(0, 6);
  const edges = objectList<EdgeItem>(payload.edges).slice(0, 8);
  const focus = textValue(payload.focus_entity) || nodes[0]?.label || "AI";
  const eyebrow = sceneEyebrow(payload, "ECOSYSTEM MAP");
  const p = spring({ fps, frame, config: { damping: 18, stiffness: 105, mass: 0.72 } });
  const displayNodes = nodes.length ? nodes : [{ id: "node_1", label: focus, role: "focus" }];
  const positions = positionsFor(displayNodes.length);

  return (
    <AbsoluteFill style={{ fontFamily: font.family, color: palette.text }}>
      <MotionBackground motif={textValue(payload.background_motif) || "device_glow"} />
      {eyebrow && (
        <div style={{ position: "absolute", left: 92, top: 74, color: palette.cyan, fontSize: 24, fontWeight: 950, letterSpacing: "0.18em", textTransform: "uppercase" }}>{eyebrow}</div>
      )}
      <div style={{ position: "absolute", left: 96, right: 96, top: eyebrow ? 126 : 96, fontSize: readableTitleSize(headline, 82), lineHeight: 0.9, fontWeight: 950, letterSpacing: "-0.06em" }}>{headline}</div>
      <svg viewBox="0 0 1920 820" style={{ position: "absolute", left: 0, right: 0, top: 238, height: 820, overflow: "visible" }}>
        {edges.map((edge, index) => {
          const fromId = edge.from || edge.source || "";
          const toId = edge.to || edge.target || "";
          const fromIndex = nodeIndexFor(displayNodes, fromId);
          const toIndex = nodeIndexFor(displayNodes, toId);
          const from = positions[fromIndex] || positions[0];
          const to = positions[toIndex] || positions[(index + 1) % positions.length];
          const opacity = clamp01(interpolate(frame, [24 + index * 5, 42 + index * 5], [0, 1], { extrapolateRight: "clamp" }));
          const label = shortDisplayText(textValue(edge.label), 22);
          const labelY = (from.y + to.y) / 2 + (index % 2 === 0 ? -42 : 32);
          return (
            <g key={`${edge.from}-${edge.to}-${index}`} opacity={opacity}>
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="rgba(99,215,255,0.42)" strokeWidth="6" strokeLinecap="round" />
              <circle cx={from.x + (to.x - from.x) * clamp01(interpolate(frame, [48 + index * 5, 92 + index * 5], [0, 1], { extrapolateRight: "clamp" }))} cy={from.y + (to.y - from.y) * clamp01(interpolate(frame, [48 + index * 5, 92 + index * 5], [0, 1], { extrapolateRight: "clamp" }))} r="8" fill={palette.amber} />
              {label && (
                <foreignObject x={(from.x + to.x) / 2 - 126} y={labelY - 25} width="252" height="58">
                  <div style={{ color: "#d9e7f7", textAlign: "center", fontSize: 24, lineHeight: 1, fontWeight: 850, background: "rgba(7,13,22,0.86)", border: "1px solid rgba(255,255,255,0.14)", borderRadius: 999, padding: "10px 14px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</div>
                </foreignObject>
              )}
            </g>
          );
        })}
        {displayNodes.map((node, index) => {
          const pos = positions[index] || positions[0];
          const opacity = clamp01(interpolate(frame, [12 + index * 10, 28 + index * 10], [0, 1], { extrapolateRight: "clamp" }));
          const isFocus = node.label === focus || node.role === "focus" || index === 0;
          const width = isFocus ? 420 : 340;
          const height = isFocus ? 148 : 126;
          const role = shortDisplayText(textValue(node.role), 22);
          const label = shortDisplayText(textValue(node.label) || "AI", isFocus ? 34 : 28);
          return (
            <g key={`${node.id}-${index}`} opacity={opacity} transform={`translate(${pos.x}, ${pos.y}) scale(${interpolate(p, [0, 1], [0.94, 1])})`}>
              <rect x={-width / 2} y={-height / 2} width={width} height={height} rx={38} fill={isFocus ? `${palette.cyan}30` : "rgba(255,255,255,0.11)"} stroke={isFocus ? palette.cyan : "rgba(255,255,255,0.26)"} strokeWidth={isFocus ? 5 : 3} />
              <circle cx={-width / 2 + 42} cy={-height / 2 + 42} r={12} fill={isFocus ? palette.cyan : palette.amber} />
              <foreignObject x={-width / 2 + 34} y={-height / 2 + 30} width={width - 68} height={height - 24}>
                <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", height: "100%", color: palette.text, textAlign: "center", fontSize: readableBodySize(label, isFocus ? 42 : 35), lineHeight: 0.96, fontWeight: 940, letterSpacing: "-0.045em" }}>
                  <div>{label}</div>
                  {role && <div style={{ marginTop: 12, color: isFocus ? palette.cyan : palette.muted, fontSize: isFocus ? 22 : 19, lineHeight: 1, fontWeight: 860, textTransform: "uppercase", letterSpacing: "0.08em" }}>{role}</div>}
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
};
