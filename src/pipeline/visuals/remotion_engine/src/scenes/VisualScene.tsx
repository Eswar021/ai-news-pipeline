import React from "react";
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

export const VisualScene: React.FC<{ sceneSpec: VisualSceneSpec }> = ({ sceneSpec }) => {
  const kind = sceneSpec.scene.render_kind;
  if (kind === "source_article_scene") {
    return <SourceArticleScene spec={sceneSpec} />;
  }
  if (kind === "context_image_scene" || kind === "broll_video_scene") {
    return <ContextMediaScene spec={sceneSpec} />;
  }
  if (kind === "logo_reveal_scene") {
    return <LogoRevealScene spec={sceneSpec} />;
  }
  if (kind === "bullet_build_scene") {
    return <BulletBuildScene spec={sceneSpec} />;
  }
  if (kind === "quote_or_claim_highlight_scene") {
    return <QuoteOrClaimHighlightScene spec={sceneSpec} />;
  }
  if (kind === "entity_compare_scene") {
    return <EntityCompareScene spec={sceneSpec} />;
  }
  if (kind === "recap_sequence_scene") {
    return <RecapSequenceScene spec={sceneSpec} />;
  }
  if (kind === "data_counter_scene") {
    return <DataCounterScene spec={sceneSpec} />;
  }
  if (kind === "trend_line_scene") {
    return <TrendLineScene spec={sceneSpec} />;
  }
  if (kind === "bar_chart_scene") {
    return <BarChartScene spec={sceneSpec} />;
  }
  if (kind === "bar_race_scene") {
    return <BarRaceScene spec={sceneSpec} />;
  }
  if (kind === "ranked_list_scene") {
    return <RankedListScene spec={sceneSpec} />;
  }
  if (kind === "benchmark_delta_scene") {
    return <BenchmarkDeltaScene spec={sceneSpec} />;
  }
  if (kind === "ecosystem_map_scene") {
    return <EcosystemMapScene spec={sceneSpec} />;
  }
  if (kind === "architecture_flow_scene") {
    return <ArchitectureFlowScene spec={sceneSpec} />;
  }
  if (kind === "process_zoom_scene") {
    return <ProcessZoomScene spec={sceneSpec} />;
  }
  if (kind === "browser_walkthrough_scene") {
    return <BrowserWalkthroughScene spec={sceneSpec} />;
  }
  if (kind === "decision_tree_scene") {
    return <DecisionTreeScene spec={sceneSpec} />;
  }
  if (kind === "capability_matrix_scene") {
    return <CapabilityMatrixScene spec={sceneSpec} />;
  }
  if (kind === "timeline_zoom_scene") {
    return <TimelineZoomScene spec={sceneSpec} />;
  }
  if (kind === "document_stack_scene") {
    return <DocumentStackScene spec={sceneSpec} />;
  }
  if (kind === "signal_radar_scene") {
    return <SignalRadarScene spec={sceneSpec} />;
  }
  if (kind === "interface_transform_scene") {
    return <InterfaceTransformScene spec={sceneSpec} />;
  }
  if (kind === "transition_stinger_scene") {
    return <TransitionStingerScene spec={sceneSpec} />;
  }
  return <KineticTypeScene spec={sceneSpec} />;
};
