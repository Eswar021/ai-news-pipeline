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

export const font = {
  family: "Avenir Next, Helvetica Neue, Arial, sans-serif"
};

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
  return `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
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
