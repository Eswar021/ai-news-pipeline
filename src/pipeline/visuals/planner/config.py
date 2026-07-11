from __future__ import annotations


PACKAGE_TYPE = "visual_scene_plan"
SUPPORTED_FORMAT = "roundup"
EPISODE_DIRECTOR_PROMPT_MODULE = "episode_director"
STORY_VISUAL_PLANNER_PROMPT_MODULE = "story_visual_planner"
NEXT_MODULE = "visuals.media_discovery"

RENDER_KINDS = [
    "source_article_scene",
    "context_image_scene",
    "broll_video_scene",
    "logo_reveal_scene",
    "kinetic_type_scene",
    "bullet_build_scene",
    "quote_or_claim_highlight_scene",
    "entity_compare_scene",
    "recap_sequence_scene",
    "data_counter_scene",
    "trend_line_scene",
    "bar_chart_scene",
    "bar_race_scene",
    "ranked_list_scene",
    "benchmark_delta_scene",
    "ecosystem_map_scene",
    "architecture_flow_scene",
    "process_zoom_scene",
    "browser_walkthrough_scene",
    "decision_tree_scene",
    "capability_matrix_scene",
    "timeline_zoom_scene",
    "document_stack_scene",
    "signal_radar_scene",
    "interface_transform_scene",
    "transition_stinger_scene",
]

OLD_CARD_RENDER_KINDS = {
    "title_card",
    "timeline_card",
    "entity_card",
    "recap_card",
    "fallback_card",
    "quote_card",
    "data_card",
}

DEFAULT_MAX_SCENES = 64
DEFAULT_MIN_SCENE_SECONDS = 3.0
DEFAULT_MAX_SCENE_SECONDS = 14.0
DEFAULT_MIN_SCENES_PER_STORY = 3
DEFAULT_MAX_SCENES_PER_STORY = 8
DEFAULT_MAX_SOURCE_ARTICLE_SCENES = 20
DEFAULT_MAX_CONTEXT_IMAGE_SCENES = 16
DEFAULT_MAX_BROLL_VIDEO_SCENES = 12
DEFAULT_MAX_LOGO_REVEAL_SCENES = 24
DEFAULT_MAX_KINETIC_TYPE_SCENES = 32
DEFAULT_MAX_BULLET_BUILD_SCENES = 24
DEFAULT_MAX_QUOTE_OR_CLAIM_SCENES = 18
DEFAULT_MAX_ENTITY_COMPARE_SCENES = 16
DEFAULT_MAX_RECAP_SEQUENCE_SCENES = 8
DEFAULT_MAX_DATA_COUNTER_SCENES = 16
DEFAULT_MAX_TREND_LINE_SCENES = 16
DEFAULT_MAX_BAR_CHART_SCENES = 16
DEFAULT_MAX_BAR_RACE_SCENES = 12
DEFAULT_MAX_RANKED_LIST_SCENES = 12
DEFAULT_MAX_BENCHMARK_DELTA_SCENES = 12
DEFAULT_MAX_ECOSYSTEM_MAP_SCENES = 16
DEFAULT_MAX_ARCHITECTURE_FLOW_SCENES = 16
DEFAULT_MAX_PROCESS_ZOOM_SCENES = 12
DEFAULT_MAX_BROWSER_WALKTHROUGH_SCENES = 12
DEFAULT_MAX_DECISION_TREE_SCENES = 12
DEFAULT_MAX_CAPABILITY_MATRIX_SCENES = 12
DEFAULT_MAX_TIMELINE_ZOOM_SCENES = 12
DEFAULT_MAX_DOCUMENT_STACK_SCENES = 12
DEFAULT_MAX_SIGNAL_RADAR_SCENES = 12
DEFAULT_MAX_INTERFACE_TRANSFORM_SCENES = 12
DEFAULT_MAX_TRANSITION_STINGER_SCENES = 12
DEFAULT_MAX_CONSECUTIVE_SAME_KIND = 2
DEFAULT_MAX_RECORDS_PER_STORY = 4
DEFAULT_MAX_RECORD_CHARS = 2200

DEFAULT_VISUAL_CAPABILITIES = {
    "source_article_scene": {
        "description": "Show a real source webpage, article, blog, paper, or report as visual proof for a narration beat.",
        "best_for": [
            "source-backed details",
            "headline reveals",
            "important claims that benefit from visible provenance",
            "showing article context while the narrator explains the story",
        ],
        "required_payload_fields": [
            "url",
            "source_record_key",
            "target_text",
            "highlight_phrases",
            "crop_strategy",
            "overlay_headline",
            "motion_style",
        ],
        "avoid_when": [
            "no selected source URL exists",
            "the narration is a broad transition rather than a source-specific point",
            "the scene would become a static slide with too much text",
        ],
        "render_notes": "Use article zooms, headline/body focus, and highlight scans. Never invent URLs or quotes.",
    },
    "context_image_scene": {
        "description": "Use a real contextual photograph or editorial image that directly depicts the spoken place, object, person, product category, or physical concept.",
        "best_for": [
            "physical-world context that a chart or text scene cannot show",
            "people, devices, labs, offices, data centers, cities, hardware, or research environments",
            "visual breathing room between dense source and diagram scenes",
            "making an abstract technology story feel tangible",
        ],
        "required_payload_fields": [
            "search_queries",
            "must_show",
            "must_avoid",
            "shot_style",
            "overlay_headline",
            "motion_style",
            "show_overlay",
        ],
        "avoid_when": [
            "a source article is needed as proof",
            "the requested image would imply an event or person not supported by narration",
            "the search intent is generic AI imagery rather than a concrete visual subject",
        ],
        "render_notes": "Plan the subject and composition, not an asset URL. Media discovery selects a licensed file and the renderer uses full-bleed cinematic motion.",
    },
    "broll_video_scene": {
        "description": "Use a real short b-roll clip to depict a physical action, environment, device, workflow, infrastructure, or human context mentioned in narration.",
        "best_for": [
            "server rooms, offices, devices, robotics, labs, manufacturing, city infrastructure, or people using technology",
            "moments where real motion explains more than another text or chart scene",
            "short atmospheric bridges that remain directly related to the spoken idea",
        ],
        "required_payload_fields": [
            "search_queries",
            "must_show",
            "must_avoid",
            "shot_style",
            "overlay_headline",
            "motion_style",
            "show_overlay",
        ],
        "avoid_when": [
            "the clip would pretend to show the exact reported event",
            "the search is too broad to stay synchronized with narration",
            "a source, diagram, metric, or logo is the clearer visual",
        ],
        "render_notes": "Plan concrete b-roll subjects only. Media discovery resolves licensed footage; mute it and keep the narration audio authoritative.",
    },
    "logo_reveal_scene": {
        "description": "Use company, product, model, or platform logos/entities as a quick YouTube-style identity moment.",
        "best_for": [
            "introducing a company or product",
            "contrasting two entities",
            "moving between stories",
            "creating quick recognition without a full screenshot",
        ],
        "required_payload_fields": [
            "entities",
            "primary_entity",
            "logo_strategy",
            "companion_text",
            "motion_style",
        ],
        "avoid_when": [
            "the story is about a source claim that needs article grounding",
            "the entity is unclear",
            "the companion text would duplicate a full sentence from narration",
        ],
        "render_notes": "Prefer short companion text, logo stacks, spotlights, and pop/slide reveals.",
    },
    "kinetic_type_scene": {
        "description": "Animate short phrases from the narration with typewriter, word snap, highlight sweep, or similar motion.",
        "best_for": [
            "retention beats",
            "transitions",
            "key takeaways",
            "moments where no source screenshot or logo is the right visual",
        ],
        "required_payload_fields": [
            "phrases",
            "emphasis_words",
            "animation_style",
            "background_motif",
        ],
        "avoid_when": [
            "the phrase is too long for on-screen reading",
            "the scene would become a wall of text",
            "a source article is needed for credibility at that moment",
        ],
        "render_notes": "Keep phrases short and punchy. Use motion, emphasis, and atmosphere rather than cards.",
    },
    "bullet_build_scene": {
        "description": "Reveal two to four short narration points one by one with a dynamic headline and progress rhythm.",
        "best_for": [
            "explaining multiple points in one narration beat",
            "showing a sequence of implications",
            "turning dense narration into readable visual beats",
            "moments where the viewer should track a list without seeing a static slide",
        ],
        "required_payload_fields": [
            "headline",
            "points",
            "emphasis_words",
            "build_style",
            "background_motif",
        ],
        "avoid_when": [
            "there is only one short idea",
            "a source screenshot is needed for credibility",
            "the points would duplicate a full paragraph from narration",
        ],
        "render_notes": "Use staggered point reveals, numbered pills, and animated emphasis. Keep each point short.",
    },
    "quote_or_claim_highlight_scene": {
        "description": "Show a source screenshot with one highlighted claim, quote, number, or caution callout.",
        "best_for": [
            "source-backed claims",
            "important caveats",
            "numbers or reported details",
            "moments where screenshot plus callout is better than a plain article view",
        ],
        "required_payload_fields": [
            "url",
            "source_record_key",
            "claim_text",
            "supporting_text",
            "highlight_phrases",
            "overlay_headline",
            "motion_style",
        ],
        "avoid_when": [
            "no selected source URL exists",
            "the narration is a broad transition",
            "the claim cannot be tied to a provided source record",
        ],
        "render_notes": "Use source screenshot as the background proof layer with a large editorial callout.",
    },
    "entity_compare_scene": {
        "description": "Compare two to four companies, products, platforms, or models with logo-style tokens and short contrasting labels.",
        "best_for": [
            "Apple versus Google moments",
            "OpenAI versus Anthropic market positioning",
            "platform or model ecosystem comparisons",
            "recap beats where entities need contrast",
        ],
        "required_payload_fields": [
            "headline",
            "entities",
            "comparison_axis",
            "entity_notes",
            "motion_style",
        ],
        "avoid_when": [
            "there is only one entity",
            "a real source screenshot is more important",
            "the comparison would invent an unsupported rivalry",
        ],
        "render_notes": "Use side-by-side or stacked logo/entity tokens with short labels, not paragraphs.",
    },
    "recap_sequence_scene": {
        "description": "Build a fast closing or transition recap with multiple story beats appearing in sequence.",
        "best_for": [
            "closing summaries",
            "roundup recap sections",
            "turning many short closing sentences into matched visual beats",
            "episode-level takeaways",
        ],
        "required_payload_fields": [
            "headline",
            "recap_items",
            "final_takeaway",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "the narration is source-specific",
            "the scene would need full article proof",
        ],
        "render_notes": "Reveal recap items progressively and end on the final takeaway. This replaces generic closing kinetic text.",
    },
    "data_counter_scene": {
        "description": "Animate one to three important metrics, dates, costs, speedups, valuations, model sizes, or adoption numbers.",
        "best_for": [
            "numbers that should feel concrete",
            "reported metrics, dates, prices, costs, speedups, or percentages",
            "turning numeric narration into a visual moment",
            "quick evidence-backed scale emphasis",
        ],
        "required_payload_fields": [
            "headline",
            "metrics",
            "emphasis_label",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "the narration has no meaningful number, date, or measurable scale",
            "the value would need to be invented",
            "a source screenshot is more important for credibility",
        ],
        "render_notes": "Use animated counters, unit labels, pulse rings, and scale bars. Keep values short and directly grounded in narration or source records.",
    },
    "trend_line_scene": {
        "description": "Animate a rising, falling, volatile, or pressure-building trend line for momentum or competition beats.",
        "best_for": [
            "skyrocketing, surging, falling behind, pressure rising, race heating up",
            "market momentum, adoption momentum, cost pressure, model competition",
            "showing direction of change when exact chart data is not required",
        ],
        "required_payload_fields": [
            "headline",
            "trend_direction",
            "y_axis_label",
            "x_axis_label",
            "annotations",
            "motion_style",
        ],
        "avoid_when": [
            "the narration does not imply direction or momentum",
            "a precise quantitative chart would be misleading",
            "the scene would imply real data points not provided",
        ],
        "render_notes": "Use stylized directional charts, not fake precise market data. Label the trend as conceptual unless exact values are supplied.",
    },
    "bar_chart_scene": {
        "description": "Show two to five bars for concrete comparisons such as cost, usage, latency, funding, model size, or adoption.",
        "best_for": [
            "comparing numeric values across entities or categories",
            "making scale differences visible",
            "showing cost, latency, adoption, funding, valuation, benchmark, or capacity comparisons",
        ],
        "required_payload_fields": [
            "headline",
            "bars",
            "unit",
            "emphasis_label",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "there are no comparable values",
            "the values would need to be invented",
            "a source screenshot is more important for credibility",
        ],
        "render_notes": "Use bold horizontal bars, large labels, and display values. Keep the chart conceptual unless exact values are provided.",
    },
    "bar_race_scene": {
        "description": "Animate ranked bars changing over time or across stages to show a race, rollout, adoption shift, or competitive movement.",
        "best_for": [
            "race heating up moments",
            "adoption or market movement",
            "before-to-after comparison across multiple entities",
            "competition among companies, models, platforms, or products",
        ],
        "required_payload_fields": [
            "headline",
            "items",
            "unit",
            "leader_label",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "there is no change or ranking implied",
            "the bars would suggest precise data not present",
        ],
        "render_notes": "Animate start-to-end values with rank movement. Use synthetic relative values only when clearly conceptual.",
    },
    "ranked_list_scene": {
        "description": "Show a fast top-three or top-five ranked list with large rank numbers, compact entity labels, and short details.",
        "best_for": [
            "top tools, models, risks, reasons, or takeaways",
            "ordered implications",
            "fast editorial ranking moments",
        ],
        "required_payload_fields": [
            "headline",
            "items",
            "emphasis_label",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "the narration is not actually ranking or ordering items",
            "the ranking would imply unsupported certainty",
        ],
        "render_notes": "Use it as a punchy ordered graphic, not as a paragraph list.",
    },
    "benchmark_delta_scene": {
        "description": "Show before/after or model-vs-model deltas with arrows, percentage changes, and short interpretation labels.",
        "best_for": [
            "speedups",
            "cost reductions",
            "benchmark improvements",
            "latency, accuracy, context, price, or capability deltas",
        ],
        "required_payload_fields": [
            "headline",
            "benchmarks",
            "winner_label",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "there is no measurable delta",
            "the comparison is not grounded in the script or records",
        ],
        "render_notes": "Use large delta typography and directional arrows. Keep labels short and concrete.",
    },
    "ecosystem_map_scene": {
        "description": "Show entities, products, platforms, developers, users, and clouds as connected nodes in a simple motion map.",
        "best_for": [
            "multi-entity platform stories",
            "Apple, Google, OpenAI, Anthropic, developers, apps, SDKs, users",
            "explaining who connects to whom",
            "showing ecosystem relationships without paragraphs",
        ],
        "required_payload_fields": [
            "headline",
            "nodes",
            "edges",
            "focus_entity",
            "motion_style",
        ],
        "avoid_when": [
            "there is only one meaningful entity",
            "the relationship would be invented",
            "a source screenshot is the clearer visual",
        ],
        "render_notes": "Use animated node reveals, connection pulses, and short role labels. Keep the graph small and readable.",
    },
    "architecture_flow_scene": {
        "description": "Show a technical or workflow pipeline as connected steps, such as app to SDK to model to user result.",
        "best_for": [
            "SDK/API/model/app/user flows",
            "training or deployment pipelines",
            "agent workflows",
            "cloud plus on-device architecture explanations",
        ],
        "required_payload_fields": [
            "headline",
            "steps",
            "flow_direction",
            "active_step_label",
            "motion_style",
        ],
        "avoid_when": [
            "the narration is just a headline or transition",
            "the steps would be speculative",
            "the sequence has fewer than two concrete stages",
        ],
        "render_notes": "Use animated blocks, moving packets, arrows, and highlighted active stages. Prefer diagrams over explanatory text lists.",
    },
    "process_zoom_scene": {
        "description": "Zoom into one important step in a workflow or architecture, showing the surrounding process as context and the active step as the hero.",
        "best_for": [
            "explaining one critical system stage",
            "showing where agents, APIs, SDKs, model calls, memory, tools, or deployment fit",
            "making a complex process feel tangible without showing every detail equally",
        ],
        "required_payload_fields": [
            "headline",
            "steps",
            "focus_step_label",
            "zoom_note",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "there is no clear active step",
            "the process has fewer than two concrete stages",
        ],
        "render_notes": "Make the active step large and central. Keep surrounding steps visible but secondary.",
    },
    "browser_walkthrough_scene": {
        "description": "Show a guided webpage or product-page walkthrough with viewport panels, scroll markers, and focused callouts.",
        "best_for": [
            "source pages that need more motion than a static screenshot",
            "product pages, docs, release pages, GitHub pages, or launch posts",
            "showing headline to feature to proof progression",
        ],
        "required_payload_fields": [
            "headline",
            "url",
            "walkthrough_steps",
            "focus_text",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "there is no URL or page context",
            "the narration is abstract rather than page-specific",
            "a quote highlight is more direct",
        ],
        "render_notes": "Use browser chrome, scroll rails, zoom windows, and step callouts. Treat as guided browsing, not a static article card.",
    },
    "decision_tree_scene": {
        "description": "Show branching decisions for routing, safety gates, agent choices, product strategy, or model selection.",
        "best_for": [
            "agent routing",
            "model selection",
            "safety or policy gates",
            "strategic tradeoffs",
            "if-this-then-that explanations",
        ],
        "required_payload_fields": [
            "headline",
            "root_label",
            "branches",
            "selected_path_label",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "there is no meaningful choice or branch",
            "the branching would invent hidden logic",
        ],
        "render_notes": "Use glowing branch paths and one highlighted route. Keep labels short.",
    },
    "capability_matrix_scene": {
        "description": "Compare products, models, or platforms across capability dimensions such as speed, cost, context, multimodal support, and tooling.",
        "best_for": [
            "model or product comparisons",
            "capability tradeoffs",
            "platform positioning",
            "viewer decision support",
        ],
        "required_payload_fields": [
            "headline",
            "columns",
            "rows",
            "highlight_cell",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "there are no comparable dimensions",
            "ratings would imply unsupported precision",
        ],
        "render_notes": "Use compact cells, check/pulse states, and one highlighted capability. Avoid dense spreadsheets.",
    },
    "timeline_zoom_scene": {
        "description": "Show a short sequence of events, then zoom into the critical event that changes the story.",
        "best_for": [
            "launch sequence",
            "follow-up events",
            "date-based story arcs",
            "before and after context",
        ],
        "required_payload_fields": [
            "headline",
            "events",
            "focus_event_label",
            "zoom_note",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "the sequence would become a generic timeline",
            "there are not at least two meaningful events",
        ],
        "render_notes": "Use a cinematic event rail and zoom into one event. Never make this a static timeline card.",
    },
    "document_stack_scene": {
        "description": "Show reports, papers, release notes, GitHub issues, docs, or source documents as layered evidence cards with parallax motion.",
        "best_for": [
            "multiple source records",
            "research or documentation-heavy stories",
            "evidence stacks",
            "showing that several documents point in the same direction",
        ],
        "required_payload_fields": [
            "headline",
            "documents",
            "focus_document_label",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "there is only one source and a source screenshot would be clearer",
            "document labels would be invented",
        ],
        "render_notes": "Use layered pages, source labels, and parallax. Keep document cards visual, not text-heavy.",
    },
    "signal_radar_scene": {
        "description": "Show a scanning radar-like field for emerging signals, companies, topics, risks, or watchlist items.",
        "best_for": [
            "watch this trend",
            "emerging signal",
            "multiple weak signals",
            "market or ecosystem sensing",
        ],
        "required_payload_fields": [
            "headline",
            "signals",
            "scan_label",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "the narration needs source proof rather than signal framing",
            "signals would be vague labels without context",
        ],
        "render_notes": "Use a radar sweep, pulsing blips, and short labels. This is for attention and sensing moments.",
    },
    "interface_transform_scene": {
        "description": "Show a before/after interface or workflow transformation, such as chat to agent workflow or manual process to automated tool loop.",
        "best_for": [
            "AI moves from chat to workflow",
            "manual to automated transformation",
            "old UI versus new UI",
            "productivity workflow changes",
        ],
        "required_payload_fields": [
            "headline",
            "before",
            "after",
            "transformation_label",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "there is no before/after contrast",
            "the visual would imply a real UI that is not shown",
        ],
        "render_notes": "Use two interface panels, connector motion, and transformation glow. Make it conceptual unless real UI assets are supplied.",
    },
    "transition_stinger_scene": {
        "description": "Create a short high-energy motion bumper between stories or visual sections using abstract newsroom graphics, entity hints, and one compact label.",
        "best_for": [
            "story-to-story transitions",
            "tempo resets",
            "brief visual breaths between dense source or diagram scenes",
            "setting up the next story without creating a static title card",
        ],
        "required_payload_fields": [
            "transition_label",
            "subtitle",
            "motion_style",
            "background_motif",
        ],
        "avoid_when": [
            "the narration is making a source-specific claim",
            "the scene would last longer than a short transition beat",
            "a real article, logo, chart, map, or flow would explain the moment better",
        ],
        "render_notes": "Keep it short, kinetic, and cinematic. This is a motion bumper, not a title card.",
    },
}
