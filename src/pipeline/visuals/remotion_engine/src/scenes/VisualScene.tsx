import React from "react";
import { AbsoluteFill } from "remotion";
import { VisualSceneSpec } from "./types";
import { SourceArticleScene } from "./SourceArticleScene";
import { LogoRevealScene } from "./LogoRevealScene";
import { KineticTypeScene } from "./KineticTypeScene";
import { BulletBuildScene } from "./BulletBuildScene";
import { QuoteOrClaimHighlightScene } from "./QuoteOrClaimHighlightScene";
import { EntityCompareScene } from "./EntityCompareScene";
import { RecapSequenceScene } from "./RecapSequenceScene";
import { DataCounterScene } from "./DataCounterScene";
import { TrendLineScene } from "./TrendLineScene";
import { BarChartScene } from "./BarChartScene";
import { BarRaceScene } from "./BarRaceScene";
import { RankedListScene } from "./RankedListScene";
import { BenchmarkDeltaScene } from "./BenchmarkDeltaScene";
import { EcosystemMapScene } from "./EcosystemMapScene";
import { ArchitectureFlowScene } from "./ArchitectureFlowScene";
import { ProcessZoomScene } from "./ProcessZoomScene";
import { BrowserWalkthroughScene } from "./BrowserWalkthroughScene";
import { DecisionTreeScene } from "./DecisionTreeScene";
import { CapabilityMatrixScene } from "./CapabilityMatrixScene";
import { TimelineZoomScene } from "./TimelineZoomScene";
import { DocumentStackScene } from "./DocumentStackScene";
import { SignalRadarScene } from "./SignalRadarScene";
import { InterfaceTransformScene } from "./InterfaceTransformScene";
import { TransitionStingerScene } from "./TransitionStingerScene";
import { ContextMediaScene } from "./ContextMediaScene";
import { EditorialTextScene } from "./EditorialTextScene";
import { SimpleExplainerScene } from "./SimpleExplainerScene";
import { StoryTransitionScene } from "./StoryTransitionScene";
import { designCanvas, editorialStyle, isEditorialMinimal, palette } from "./style";

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
  } else if (kind === "bullet_build_scene") {
    scene = <BulletBuildScene spec={sceneSpec} />;
  } else if (kind === "quote_or_claim_highlight_scene") {
    scene = <QuoteOrClaimHighlightScene spec={sceneSpec} />;
  } else if (kind === "entity_compare_scene") {
    scene = <EntityCompareScene spec={sceneSpec} />;
  } else if (kind === "recap_sequence_scene") {
    scene = <RecapSequenceScene spec={sceneSpec} />;
  } else if (kind === "data_counter_scene") {
    scene = <DataCounterScene spec={sceneSpec} />;
  } else if (kind === "trend_line_scene") {
    scene = <TrendLineScene spec={sceneSpec} />;
  } else if (kind === "bar_chart_scene") {
    scene = <BarChartScene spec={sceneSpec} />;
  } else if (kind === "bar_race_scene") {
    scene = <BarRaceScene spec={sceneSpec} />;
  } else if (kind === "ranked_list_scene") {
    scene = <RankedListScene spec={sceneSpec} />;
  } else if (kind === "benchmark_delta_scene") {
    scene = <BenchmarkDeltaScene spec={sceneSpec} />;
  } else if (kind === "ecosystem_map_scene") {
    scene = <EcosystemMapScene spec={sceneSpec} />;
  } else if (kind === "architecture_flow_scene") {
    scene = <ArchitectureFlowScene spec={sceneSpec} />;
  } else if (kind === "process_zoom_scene") {
    scene = <ProcessZoomScene spec={sceneSpec} />;
  } else if (kind === "browser_walkthrough_scene") {
    scene = <BrowserWalkthroughScene spec={sceneSpec} />;
  } else if (kind === "decision_tree_scene") {
    scene = <DecisionTreeScene spec={sceneSpec} />;
  } else if (kind === "capability_matrix_scene") {
    scene = <CapabilityMatrixScene spec={sceneSpec} />;
  } else if (kind === "timeline_zoom_scene") {
    scene = <TimelineZoomScene spec={sceneSpec} />;
  } else if (kind === "document_stack_scene") {
    scene = <DocumentStackScene spec={sceneSpec} />;
  } else if (kind === "signal_radar_scene") {
    scene = <SignalRadarScene spec={sceneSpec} />;
  } else if (kind === "interface_transform_scene") {
    scene = <InterfaceTransformScene spec={sceneSpec} />;
  } else if (kind === "transition_stinger_scene") {
    scene = <TransitionStingerScene spec={sceneSpec} />;
  } else {
    scene = <KineticTypeScene spec={sceneSpec} />;
  }

  const outputWidth = Math.max(1, Number(sceneSpec.width || designCanvas.width));
  const outputHeight = Math.max(1, Number(sceneSpec.height || designCanvas.height));
  const scale = Math.min(outputWidth / designCanvas.width, outputHeight / designCanvas.height);
  const left = (outputWidth - designCanvas.width * scale) / 2;
  const top = (outputHeight - designCanvas.height * scale) / 2;
  const background = isEditorialMinimal(sceneSpec.visual_style)
    ? editorialStyle(sceneSpec.visual_style).background
    : palette.bg;

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
