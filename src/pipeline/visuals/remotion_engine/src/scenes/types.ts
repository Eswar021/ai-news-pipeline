export type RenderKind =
  | "source_article_scene"
  | "context_image_scene"
  | "broll_video_scene"
  | "logo_reveal_scene"
  | "editorial_text_scene"
  | "simple_explainer_scene"
  | "story_transition_scene"
  | "quote_or_claim_highlight_scene"
  | "browser_walkthrough_scene"
  | "document_stack_scene"
  | "interface_transform_scene";

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
    quality_class?: string;
    primary_entity?: string;
    simple_icon_export?: string;
    fallback_svg_path?: string;
  };
  capture?: Record<string, unknown>;
  assets?: Array<{
    asset_id?: string;
    source_record_key?: string;
    source_url?: string;
    title?: string;
    source?: string;
    domain?: string;
    asset_path?: string;
    asset_data_uri?: string;
    asset_render_url?: string;
    status?: string;
    capture?: Record<string, unknown>;
  }>;
};

export type VisualScenePayload = Record<string, unknown>;

export type VisualStyleSpec = {
  style_id?: string;
  background_color?: string;
  text_color?: string;
  accent_color?: string;
  muted_color?: string;
  editorial_font?: string;
  sans_font?: string;
  surface_treatment?: string;
  card_policy?: string;
};

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
  visual_style?: VisualStyleSpec;
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
