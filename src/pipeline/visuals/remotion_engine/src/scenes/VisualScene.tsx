import React from "react";
import { AbsoluteFill } from "remotion";
import { VisualSceneSpec } from "./types";
import { SourceArticleScene } from "./SourceArticleScene";
import { LogoRevealScene } from "./LogoRevealScene";
import { QuoteOrClaimHighlightScene } from "./QuoteOrClaimHighlightScene";
import { BrowserWalkthroughScene } from "./BrowserWalkthroughScene";
import { DocumentStackScene } from "./DocumentStackScene";
import { InterfaceTransformScene } from "./InterfaceTransformScene";
import { ContextMediaScene } from "./ContextMediaScene";
import { EditorialTextScene } from "./EditorialTextScene";
import { SimpleExplainerScene } from "./SimpleExplainerScene";
import { StoryTransitionScene } from "./StoryTransitionScene";
import { SourceProofMontageScene } from "./SourceProofMontageScene";
import { designCanvas, editorialStyle } from "./style";

export const VisualScene: React.FC<{ sceneSpec: VisualSceneSpec }> = ({ sceneSpec }) => {
  const kind = sceneSpec.scene.render_kind;
  let scene: React.ReactNode;
  if (kind === "source_article_scene") {
    scene = <SourceArticleScene spec={sceneSpec} />;
  } else if (kind === "context_image_scene" || kind === "broll_video_scene") {
    scene = <ContextMediaScene spec={sceneSpec} />;
  } else if (kind === "logo_reveal_scene") {
    scene = <LogoRevealScene spec={sceneSpec} />;
  } else if (kind === "editorial_text_scene") {
    scene = <EditorialTextScene spec={sceneSpec} />;
  } else if (kind === "simple_explainer_scene") {
    scene = <SimpleExplainerScene spec={sceneSpec} />;
  } else if (kind === "story_transition_scene") {
    scene = <StoryTransitionScene spec={sceneSpec} />;
  } else if (kind === "quote_or_claim_highlight_scene") {
    scene = <QuoteOrClaimHighlightScene spec={sceneSpec} />;
  } else if (kind === "browser_walkthrough_scene") {
    scene = <BrowserWalkthroughScene spec={sceneSpec} />;
  } else if (kind === "document_stack_scene") {
    scene = sceneSpec.scene.payload?.recipe_id === "source_proof_montage"
      ? <SourceProofMontageScene spec={sceneSpec} />
      : <DocumentStackScene spec={sceneSpec} />;
  } else if (kind === "interface_transform_scene") {
    scene = <InterfaceTransformScene spec={sceneSpec} />;
  } else {
    const unsupportedKind: never = kind;
    throw new Error(`Unsupported render kind: ${unsupportedKind}`);
  }

  const outputWidth = Math.max(1, Number(sceneSpec.width || designCanvas.width));
  const outputHeight = Math.max(1, Number(sceneSpec.height || designCanvas.height));
  const scale = Math.min(outputWidth / designCanvas.width, outputHeight / designCanvas.height);
  const left = (outputWidth - designCanvas.width * scale) / 2;
  const top = (outputHeight - designCanvas.height * scale) / 2;
  const background = editorialStyle(sceneSpec.visual_style).background;

  return (
    <AbsoluteFill style={{ background, overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          left,
          top,
          width: designCanvas.width,
          height: designCanvas.height,
          transform: `scale(${scale})`,
          transformOrigin: "top left",
          overflow: "hidden",
        }}
      >
        {scene}
      </div>
    </AbsoluteFill>
  );
};
