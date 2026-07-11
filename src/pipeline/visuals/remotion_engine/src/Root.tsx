import React from "react";
import { Composition } from "remotion";
import { VisualScene } from "./scenes/VisualScene";
import { VisualSceneSpec } from "./scenes/types";

const defaultSceneSpec: VisualSceneSpec = {
  width: 1920,
  height: 1080,
  fps: 30,
  duration_seconds: 6,
  scene: {
    scene_id: "scene_preview",
    render_kind: "kinetic_type_scene",
    payload: {
      phrases: ["AI NEWS SHIFT"],
      emphasis_words: ["AI"],
      animation_style: "typewriter",
      background_motif: "newsroom_grid"
    },
    script_excerpt: "Preview scene",
    visual_intent: "Preview",
    resolved_asset: {}
  }
};

export const Root: React.FC = () => {
  return (
    <Composition
      id="VisualScene"
      component={VisualScene}
      durationInFrames={180}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{ sceneSpec: defaultSceneSpec }}
    />
  );
};
