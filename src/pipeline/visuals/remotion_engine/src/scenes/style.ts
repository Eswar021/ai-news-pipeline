export const palette = {
  bg: "#070b10",
  panel: "rgba(13, 22, 34, 0.82)",
  panelStrong: "rgba(7, 13, 22, 0.94)",
  text: "#f7fbff",
  muted: "#9fb2c7",
  cyan: "#63d7ff",
  amber: "#ffcf70",
  red: "#ff5c7a",
  green: "#8df7bd"
};

// Scene components use one stable design grid. The root renderer scales this
// canvas to the requested 16:9 output so 720p, 1080p, 2K, and 4K preserve the
// same composition instead of exposing fixed-coordinate clipping.
export const designCanvas = {
  width: 1920,
  height: 1080,
};

export const font = {
  family: "Avenir Next, Helvetica Neue, Arial, sans-serif"
};

export const editorialDefaults = {
  background: "#f4efe6",
  text: "#171611",
  accent: "#bd4e2f",
  muted: "#6f6a61",
  editorialFont: "Iowan Old Style, Baskerville, Georgia, Times New Roman, serif",
  sansFont: "Avenir Next Condensed, Avenir Next, Helvetica Neue, Arial, sans-serif",
};

export const isEditorialMinimal = (style?: VisualStyleSpec) => style?.style_id === "editorial_minimal";

export const editorialStyle = (style?: VisualStyleSpec) => ({
  background: style?.background_color || editorialDefaults.background,
  text: style?.text_color || editorialDefaults.text,
  accent: style?.accent_color || editorialDefaults.accent,
  muted: style?.muted_color || editorialDefaults.muted,
  editorialFont: style?.editorial_font || editorialDefaults.editorialFont,
  sansFont: style?.sans_font || editorialDefaults.sansFont,
});

export const clamp01 = (value: number) => Math.max(0, Math.min(1, value));

export const textValue = (value: unknown) => (typeof value === "string" ? value.trim() : "");

export const listValue = (value: unknown) => (Array.isArray(value) ? value.map(String).map((item) => item.trim()).filter(Boolean) : []);

export type VisualBeat = {
  unit_order?: number;
  start_seconds?: number;
  end_seconds?: number;
  relative_start_seconds?: number;
  relative_end_seconds?: number;
  text?: string;
  visual_action?: string;
  emphasis_words?: string[];
};

export const beatList = (value: unknown): VisualBeat[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    .map((item) => ({
      unit_order: typeof item.unit_order === "number" ? item.unit_order : undefined,
      start_seconds: typeof item.start_seconds === "number" ? item.start_seconds : undefined,
      end_seconds: typeof item.end_seconds === "number" ? item.end_seconds : undefined,
      relative_start_seconds: typeof item.relative_start_seconds === "number" ? item.relative_start_seconds : undefined,
      relative_end_seconds: typeof item.relative_end_seconds === "number" ? item.relative_end_seconds : undefined,
      text: textValue(item.text),
      visual_action: textValue(item.visual_action),
      emphasis_words: listValue(item.emphasis_words),
    }))
    .filter((beat) => Boolean(beat.text || beat.visual_action));
};

export const shortDisplayText = (value: string, max = 72) => {
  const text = value.trim();
  if (text.length <= max) {
    return text;
  }
  const candidate = text.slice(0, Math.max(0, max - 1)).trimEnd();
  const wordBoundary = candidate.lastIndexOf(" ");
  const shortened = wordBoundary >= Math.floor(max * 0.55)
    ? candidate.slice(0, wordBoundary).trimEnd()
    : candidate;
  return `${shortened}…`;
};

export const readableBodySize = (text: string, base = 34) => {
  if (text.length > 110) {
    return base * 0.76;
  }
  if (text.length > 78) {
    return base * 0.84;
  }
  if (text.length > 48) {
    return base * 0.92;
  }
  return base;
};

export const sceneEyebrow = (payload: Record<string, unknown>, fallback = "") => {
  const explicit = textValue(payload.eyebrow);
  if (explicit) {
    return explicit;
  }
  return payload.show_scene_label === true ? fallback : "";
};

export const readableTitleSize = (text: string, base = 92) => {
  if (text.length > 64) {
    return base * 0.72;
  }
  if (text.length > 42) {
    return base * 0.82;
  }
  if (text.length > 26) {
    return base * 0.92;
  }
  return base;
};
import type { VisualStyleSpec } from "./types";
