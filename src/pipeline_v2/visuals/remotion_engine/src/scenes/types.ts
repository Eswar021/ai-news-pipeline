export type RenderKind =
  | "source_article_scene"
  | "context_image_scene"
  | "broll_video_scene"
  | "logo_reveal_scene"
  | "kinetic_type_scene"
  | "bullet_build_scene"
  | "quote_or_claim_highlight_scene"
  | "entity_compare_scene"
  | "recap_sequence_scene"
  | "data_counter_scene"
  | "trend_line_scene"
  | "bar_chart_scene"
  | "bar_race_scene"
  | "ranked_list_scene"
  | "benchmark_delta_scene"
  | "ecosystem_map_scene"
  | "architecture_flow_scene"
  | "process_zoom_scene"
  | "browser_walkthrough_scene"
  | "decision_tree_scene"
  | "capability_matrix_scene"
  | "timeline_zoom_scene"
  | "document_stack_scene"
  | "signal_radar_scene"
  | "interface_transform_scene"
  | "transition_stinger_scene";

export type ResolvedAsset = {
  asset_type?: string;
  status?: string;
  asset_path?: string;
  asset_data_uri?: string;
  asset_public_path?: string;
  media?: {
    provider?: string;
    media_type?: string;
    duration_seconds?: number;
    attribution?: string;
    license?: string;
    source_url?: string;
  };
  logo?: {
    logo_source?: string;
    primary_entity?: string;
    simple_icon_export?: string;
    fallback_svg_path?: string;
  };
  capture?: Record<string, unknown>;
};

export type VisualScenePayload = Record<string, unknown>;

export type VisualSceneSpec = {
  width: number;
  height: number;
  fps: number;
  codec?: string;
  crf?: number | null;
  video_bitrate?: string | null;
  x264_preset?: string | null;
  pixel_format?: string | null;
  duration_seconds: number;
  scene: {
    scene_id: string;
    scene_order?: number;
    story_id?: string;
    start_seconds?: number;
    end_seconds?: number;
    duration_seconds?: number;
    render_kind: RenderKind;
    script_excerpt?: string;
    visual_intent?: string;
    payload: VisualScenePayload;
    resolved_asset?: ResolvedAsset;
  };
};
