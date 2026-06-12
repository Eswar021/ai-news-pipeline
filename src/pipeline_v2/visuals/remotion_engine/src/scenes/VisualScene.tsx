import React from "react";
import { VisualSceneSpec } from "./types";
import { SourceArticleScene } from "./SourceArticleScene";
import { LogoRevealScene } from "./LogoRevealScene";
import { KineticTypeScene } from "./KineticTypeScene";

export const VisualScene: React.FC<{ sceneSpec: VisualSceneSpec }> = ({ sceneSpec }) => {
  const kind = sceneSpec.scene.render_kind;
  if (kind === "source_article_scene") {
    return <SourceArticleScene spec={sceneSpec} />;
  }
  if (kind === "logo_reveal_scene") {
    return <LogoRevealScene spec={sceneSpec} />;
  }
  return <KineticTypeScene spec={sceneSpec} />;
};

