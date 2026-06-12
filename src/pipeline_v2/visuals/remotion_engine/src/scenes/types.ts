export type RenderKind = "source_article_scene" | "logo_reveal_scene" | "kinetic_type_scene";

export type ResolvedAsset = {
  asset_type?: string;
  status?: string;
  asset_path?: string;
  asset_data_uri?: string;
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

