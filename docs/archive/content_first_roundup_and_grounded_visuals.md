# Creator-Led AI News Roundup and Grounded Visuals Redesign

Status: Archived product-design and research record. Do not use this file as
the active implementation tracker; current work is tracked in
`docs/build/production_orchestration_and_creative_quality_worklist.md`.

Last reviewed: 2026-07-17

Target runtime: src/pipeline/

Reference run: run_2026_07_13_014243_daily_48h_all_sources

## 1. Executive Decision

The target is not an article-reading system. It is a creator-led YouTube
storytelling system.

The central rule is:

    Sources constrain what is true.
    The editorial system decides what is interesting.
    The writer decides how to make it clear, memorable, and entertaining.

Source grounding is an invisible production rail. It must not become the
spoken style, the story outline, or the main quality objective. A viewer should
hear a confident narrator with a recognizable point of view, not a model
reciting a list of article facts.

The LLM is valuable because it should do work that deterministic extraction
cannot:

- Find the tension, contradiction, surprise, or human consequence in a story.
- Connect several facts into one meaningful idea.
- Decide which details deserve attention and which can be omitted.
- Translate technical mechanisms into plain-language mental models.
- Create fitting analogies, observational humor, callbacks, and punchlines.
- Express a useful editorial opinion without fabricating personal experience.
- Build curiosity, vary rhythm, and deliver a satisfying payoff.
- Connect stories when a genuine relationship exists without inventing one for
  a heterogeneous roundup.

The system should be source-grounded but creator-led. Those are complementary,
not competing, goals.

### Current implementation decision

Phase 2.3 supersedes the earlier deterministic prose-scoring proposals in this
document. Code must not decide whether generated narration is engaging,
corporate, overclaimed, sufficiently attributed, or semantically similar to a
source by using keyword lists, regexes, overlap thresholds, or metric matching.
Those are categorical editorial judgments for the LLM director/reviewer and
human review.

The runtime keeps only objective integrity checks: schema, selected-story and
source ownership, known IDs, section/beat order, non-empty narration,
deterministic projections, bounded review loops, and artifact provenance. The
older phase descriptions remain below as design history, not current runtime
requirements.

The reference episode's roughly 4:19 duration is acceptable. A strong two-,
three-, or four-minute episode is better than a padded eight-minute episode.
Duration remains observational. Content quality, viewer value, and natural
completion own the ending.

## 2. Research Method

This redesign is informed by a qualitative study of public captions,
metadata, and sampled video frames from representative established technology
and AI channels. The study was performed on 2026-07-13.

The sample included:

| Channel | Representative video | Runtime | Approximate caption pace |
| --- | --- | ---: | ---: |
| Fireship | [Google's AI endgame is here... everything you missed at I/O 2026](https://www.youtube.com/watch?v=9OQ5vaYbGV0) | 5:43 | 203 WPM |
| Fireship | [10 weird OSS projects you need right now...](https://www.youtube.com/watch?v=qPuzWFvRajk) | 7:02 | 195 WPM |
| TechLinked | [You Just Don't Get It](https://www.youtube.com/watch?v=znuFb4eE9nc) | 8:43 | 175 WPM |
| Matt Wolfe | [AI News: An INSANE Week... Here's What Matters](https://www.youtube.com/watch?v=nydHKXjwu0U) | 30:51 | 204 WPM |
| Two Minute Papers | [DeepSeek Just Solved AI's Billion Dollar Problem](https://www.youtube.com/watch?v=mG4SmhWyeFA) | 5:50 | 157 WPM |

The WPM values are approximate measurements from public captions and include
normal caption errors, sponsors, and outros. They describe the sample. They
are not targets for this pipeline.

The analysis examined:

- The first 30 seconds.
- Story openings and transitions.
- How facts, opinions, jokes, and explanations were interleaved.
- Sentence rhythm and question use.
- How technical ideas were made accessible.
- What appeared on screen during factual, explanatory, and humorous moments.
- How stories ended and moved to the next item.

This is a qualitative design study, not proof that any single technique caused
a video's performance. We should test the resulting design against our own
audience retention data after publishing.

No full third-party transcripts should be committed to this repository. The
repository should retain only derived design observations and links to the
original videos.

## 3. What the Channel Study Shows

### 3.1 Strong creators do not follow article order

The sampled scripts rarely sound like:

    Company announced X.
    The article also says Y.
    The report states Z.
    This is important for the industry.

Instead, the creator chooses a premise.

Fireship reframes a keynote as a broader strategy and uses each announcement
as evidence for that interpretation. TechLinked frames a product launch as a
conflict between the product's promise, its defenders, and the actual user
experience. Two Minute Papers begins with a technical paradox, then resolves
it through a simple mental model. Matt Wolfe curates what matters, offers a
personal reaction, and demonstrates products rather than merely listing them.

The article supplies facts. The creator supplies the story.

### 3.2 Each story has a mini-arc

Across the sample, a strong story commonly follows a flexible arc:

    hook or tension
      -> what changed
      -> the surprising or confusing part
      -> explanation, example, or demonstration
      -> creator reaction or comic release
      -> consequence for the viewer
      -> payoff or forward-looking question

Not every story uses every step. A brief may use only surprise, explanation,
and consequence. A lead may develop the full arc.

The important property is movement. A story should not feel like several facts
placed next to each other.

### 3.3 Personality is structural, not decorative

Personality is not created by adding one joke after a dry summary. It appears
throughout the editorial choices:

- What the narrator finds absurd, impressive, worrying, or overhyped.
- Which contradiction becomes the story's center.
- The analogy used to explain a mechanism.
- A short reaction after a dense fact.
- Self-aware or observational humor.
- A callback to an earlier story or running episode motif.
- A clear opinion about what actually matters.

Fireship uses compressed absurd comparisons and developer-specific jokes.
TechLinked combines reporting with presenter reactions and comedic tags.
Matt Wolfe uses first-person curation and live product demonstrations.
Two Minute Papers uses questions, optimism, playful thought experiments, and
recurring enthusiasm.

We should adopt the craft behavior, not imitate their exact voice, profanity,
catchphrases, or jokes.

### 3.4 Facts are selected for narrative work

Strong scripts do not maximize fact count. They select facts that perform a
job:

- A number creates scale.
- A contradiction creates tension.
- A product behavior makes the story tangible.
- A benchmark supports or challenges the marketing.
- A quote exposes a company's position.
- A limitation changes how the viewer interprets the claim.

One memorable fact inside a strong explanation can be more valuable than six
metrics read consecutively.

The writer therefore needs access to rich source material, but it should be
asked to choose the most narratively useful details, not to mention every
available detail.

### 3.5 Explanation creates value beyond the news

Two Minute Papers is the clearest example of turning a technical mechanism into
a mental model. It uses questions and analogies to let the viewer predict the
answer before revealing it.

Fireship often gives the developer-level mechanism after a joke or provocative
claim. Matt Wolfe shows the actual product and reacts to what it does. The
viewer receives both information and understanding.

Our story writer must answer more than "what happened":

- What is the simplest useful model of how this works?
- Why did the old approach fail or become insufficient?
- What changes for a developer, company, user, or creator?
- What should the viewer watch next?

### 3.6 Rhythm matters more than a universal speed target

The sampled videos ranged from about 157 to 204 caption words per minute.
They remain engaging through different methods.

Useful rhythm patterns include:

- A longer setup followed by a short punchline.
- A question followed by a concrete answer.
- Dense explanation followed by a reaction or visual breath.
- A serious consequence followed by restrained humor.
- A quick brief after a longer lead story.

The target is sentence and idea variation, not maximum WPM.

### 3.7 Their visuals show, explain, and react

The visual samples were not dominated by generated cards.

Fireship used keynote footage, product interfaces, real charts, code, article
or documentation captures, reaction clips, and simple comedic labels.

TechLinked used presenter continuity, source articles, product images, social
posts, demonstrations, and short on-screen joke captions.

Matt Wolfe used presenter picture-in-picture, browser walkthroughs, official
product pages, demos, clips, and direct reactions.

Two Minute Papers used custom explanatory animation, paper figures, simple
diagrams, and visual analogies. Its code-generated graphics worked because
they explained the current sentence instead of decorating it.

The shared rule is not "use screenshots" or "use charts." It is:

    Show the thing when it exists.
    Explain the mechanism when it is abstract.
    React visually when the narration is reacting.
    Use text only when the words themselves are the moment.

## 4. Target Channel Voice

We need a distinct channel identity rather than a blend that sounds like a
copy of existing creators.

Recommended starting persona:

    A curious technical friend who builds with AI, enjoys useful progress,
    notices absurd marketing, and explains the important part without acting
    like every announcement changes civilization.

Recommended worldview:

- Optimistic about useful technology.
- Skeptical of marketing and unsupported certainty.
- Interested in practical consequences.
- Comfortable saying that something is clever, strange, unfinished, or
  overhyped.
- Willing to explain technical depth, but unwilling to hide behind jargon.

Recommended humor:

- Observational.
- Dry and self-aware.
- Occasional absurd analogy.
- Light developer or internet-culture references when broadly understandable.
- Short comic tags after dense material.
- Callbacks used sparingly.

Avoid:

- Corporate enthusiasm.
- Forced jokes in every beat.
- Mean-spirited attacks or punching down.
- Profanity as a substitute for a point of view.
- Fabricated first-person testing, attendance, conversations, or experience.
- Copying another creator's recognizable wording or catchphrases.

The narrator may express an editorial opinion such as "the interesting part is"
or "this looks more useful than the headline suggests." It may not say "I
tested this" unless the input contains a real test performed by the channel.

Voice should be config-driven and stable across episodes. Prompts should
describe the desired behavior, not name Fireship, TechLinked, Matt Wolfe, or
Two Minute Papers as styles to imitate.

## 5. Reference-Run Diagnosis

### 5.1 The source content was good enough

The reference run contained useful story material. The Sqlsure record alone
included a fast check, a large query test, false-alarm results, an unusual bug,
and repair results.

That does not mean the script should recite all of those values. It means the
writer had several possible story engines:

- Catching database problems before production.
- The surprising speed of the check.
- Whether a promising benchmark survives real codebases.
- The difference between a useful safety net and a guarantee.

The generated segment did not choose and develop one of those engines. It
substituted generic words such as "groundbreaking," "indispensable," and
"must-have."

### 5.2 Full records were already passed

The writer received the full selected story records. The omission was not
primarily caused by truncation or a weak model. The current script model was
openai/gpt-4o.

The confirmed design problems are:

- The director produces broad coverage notes rather than a strong story engine.
- The writer prompt describes tone but does not teach a distinctive voice.
- The output contract tracks source records but not the purpose of each beat.
- No prompt examples demonstrate opinion, analogy, humor, or a compelling
  mini-arc.
- Current checks can detect structural errors but not article-readout language,
  weak storytelling, or personality loss.

### 5.3 Review is biased toward unnecessary rewriting

The reviewer is required to produce a complete revised segment even when the
initial segment is good. This encourages change for the sake of change.

In the reference run:

- Every story reviewer proposed a rewrite.
- One reviewer had an empty diagnosis but still recommended applying a change.
- The Sqlsure revision strengthened a measured result into a false guarantee.

The review idea is correct. The contract and acceptance logic are not.

### 5.4 Visual grounding failures remain separate

The storytelling redesign does not remove the need to fix:

- A rural-school photograph selected for Tang Tan/OpenAI leadership.
- A lightning photograph selected for Instagram privacy.
- Fabricated Apple/OpenAI chart values of 100 and 80.
- Placeholder data visuals.
- A previous beat's payload copied across later scene slices.
- Too few real product, source, demo, and contextual assets.

Visual grounding should prevent wrong assets and invented data, while the
creative visual planner decides how to make the correct beat interesting.

## 6. Design Principles

### 6.1 Truth is a boundary, not a writing template

The system should index source truth so claims can be traced and checked. It
must not require the spoken script to mirror source sentences or source order.

### 6.2 The story engine comes before the fact list

Before writing prose, the director chooses the story's central engine:

- contradiction
- surprise
- practical consequence
- problem and solution
- competition
- human behavior
- technical mechanism
- strategic shift
- cautionary failure

Facts are selected because they advance that engine.

### 6.3 Creativity has explicit permission

The writer is allowed to create:

- Analogies.
- Hypothetical scenarios.
- Rhetorical questions.
- Observational jokes.
- Short comic tags.
- Editorial opinions.
- Cross-story connections.
- Episode callbacks.
- Plain-language explanations.

These devices do not need source references unless they contain an externally
verifiable factual assertion.

### 6.4 Specificity beats hype

Concrete behavior, consequence, or one useful number should replace generic
importance words. The purpose is not to sound cautious. It is to sound like
the narrator actually understands why the story is interesting.

### 6.5 No forced creativity

A serious privacy, safety, or legal story may need restraint. A technical
story may need a clean analogy more than a joke. The director chooses the
appropriate creative devices for each story.

### 6.6 Content controls duration

Lead, major, and brief describe editorial depth, not fixed seconds or words.
Voiceover duration is measured after the script is accepted.

## 7. Target Architecture

    selected video packet with full records
      -> source truth index
      -> optional bounded context enrichment
      -> episode editorial director
      -> one story angle and voice brief per story
      -> parallel per-story audiovisual storytellers
      -> deterministic structure, ownership, and provenance checks
      -> conditional craft reviewers
      -> revision acceptance comparator
      -> bookend and continuity storyteller
      -> canonical section and beat script
      -> section-aware voiceover and alignment
      -> verified per-story asset catalog
      -> per-story visual storyteller
      -> asset and data validation
      -> Remotion rendering and episode assembly

Script generation remains one public app boundary. Director, storyteller,
reviewer, and bookend logic are internal modules.

Production orchestration is exposed through three thin stage routers under
`src/pipeline/orchestration/stages/` and one CLI dispatcher. This does not
return to numbered layers: each router calls the same independent app
contracts and owns only sequencing, state, paths, and logs.

## 8. Three Input Layers for Story Writing

### 8.1 Truth layer

Contains:

- Full selected records.
- Exact source URLs and record keys.
- Searchable source sentences.
- Numeric and quote candidates with original context.
- Optional authoritative context gathered before writing.

The truth layer answers "what can be asserted."

### 8.2 Editorial layer

Contains:

- Episode thesis.
- Story role and order.
- Story engine.
- Viewer stakes.
- Tension or contradiction.
- What is genuinely new.
- What the viewer should understand at the end.
- Relationship to the previous and next stories.

The editorial layer answers "what story are we telling."

### 8.3 Creative layer

Contains:

- Channel persona and worldview.
- Energy and language style.
- Allowed humor modes.
- Analogy opportunities.
- Optional callback candidates.
- Visual opportunities and real available assets.
- Story-specific creative limits.

The creative layer answers "how should this feel."

The writer needs all three. Supplying only the truth layer produces a summary.
Supplying only the creative layer produces confident nonsense.

## 9. Script Generation Contracts

### 9.1 Source truth index

Add an app-local helper:

    src/pipeline/apps/script_generation/formats/roundup/source_truth.py

This is not a public fact-packet layer and does not add an LLM extraction call.
It is invisible production metadata derived from the same full records already
provided to the writer.

Proposed shape:

    class TruthItem(BaseModel):
        truth_id: str
        record_key: str
        truth_type: Literal[
            "event", "metric", "result", "mechanism",
            "quote", "limitation", "example", "context"
        ]
        source_text: str
        source_title: str
        source_url: str
        value_text: str | None


    class StoryTruthIndex(BaseModel):
        story_id: str
        items: list[TruthItem]
        full_records: list[dict[str, Any]]

The index must scan title, summary, description, and full content. Full records
remain authoritative and present in the prompt. The index improves navigation
and traceability; it does not tell the writer to use every item.

### 9.2 Optional context enrichment

Some selected records report the event but omit the background needed for a
good explanation. Add an optional bounded research step for lead and major
stories.

It may retrieve:

- An official product page or documentation.
- A primary research paper.
- An authoritative historical comparison.
- A direct source needed to explain a disputed claim.

It must not become open-ended research.

Configuration controls:

- Enabled story roles.
- Maximum additional sources per story.
- Allowed domains or source classes.
- Search and token budgets.
- Required provenance.
- Timeout and failure behavior.

Enriched context becomes another truth source before writing. The storyteller
does not browse during prose generation.

### 9.3 Episode editorial director

The director should no longer maximize coverage. It should produce a clear
episode idea and one storytelling brief per selected story.

Proposed story brief:

    class StoryDirectionBrief(BaseModel):
        story_id: str
        story_engine: Literal[
            "contradiction", "surprise", "problem_solution",
            "practical_consequence", "competition", "human_behavior",
            "technical_mechanism", "strategic_shift", "cautionary_failure"
        ]
        story_promise: str
        hook_idea: str
        tension: str
        reveal_or_payoff: str
        viewer_stakes: str
        must_communicate_truth_ids: list[str]
        optional_truth_ids: list[str]
        narrator_take: str
        explanation_goal: str
        analogy_opportunities: list[str]
        humor_opportunities: list[str]
        humor_restraint_reason: str | None
        transition_relationship: str
        visual_payoffs: list[str]

The director chooses a small number of facts that the story cannot lose. Other
truth items remain available to the writer as optional material.

The director must not write generic instructions such as "explain why it
matters" without naming the actual tension and consequence.

### 9.4 Per-story audiovisual storyteller

Rename the conceptual responsibility from story writer to story storyteller.
The code module can remain writer.py if renaming creates unnecessary churn.

Proposed beat contract:

    BeatFunction = Literal[
        "story_hook",
        "setup",
        "reveal",
        "explanation",
        "example",
        "reaction",
        "comic_release",
        "consequence",
        "caveat",
        "payoff",
        "bridge",
    ]


    CreativeDevice = Literal[
        "none",
        "analogy",
        "contrast",
        "rhetorical_question",
        "hypothetical",
        "observational_humor",
        "self_aware_humor",
        "callback",
    ]


    class StoryBeatDraft(BaseModel):
        beat_function: BeatFunction
        narration_text: str
        support_truth_ids: list[str]
        creative_device: CreativeDevice
        visual_goal: str
        visual_brief: VisualBriefDraft

Rules:

- Externally verifiable claims use support_truth_ids.
- Pure opinion, analogy, humor, hypothetical, and transition language may use
  an empty support list.
- Support IDs never appear in spoken narration.
- A joke may not smuggle in an unsupported factual accusation.
- The writer can omit optional truth items.
- The writer should preserve the director's priority ideas when they improve
  the story, but missing an internal truth-ID reference is diagnostic rather
  than an approval quota. It may paraphrase, reorder, combine, or explain them
  naturally.
- Beats are semantic audiovisual moments, not one sentence each and not a
  fixed count.

### 9.5 Flexible story arcs by role

Lead:

- Earns the strongest opening.
- Develops tension and mechanism.
- Uses the best example, demonstration, or consequence.
- Has room for a reaction, analogy, or payoff.

Major:

- Uses a compact but complete mini-arc.
- Explains the part that changes interpretation.
- Ends with a clear consequence or open question.

Brief:

- Delivers one compelling change.
- Adds one useful interpretation, reaction, or consequence.
- Leaves before it becomes a summary dump.

No role has a hard word count or duration requirement.

### 9.6 Prompt design

The storyteller prompt must explicitly say:

- Do not summarize the record in source order.
- Do not begin with a generic introduction.
- Choose a story engine and build movement.
- Treat facts as material for tension, explanation, and payoff.
- Use a few strong details rather than listing everything.
- Add personality through viewpoint, rhythm, analogy, or fitting humor.
- Explain jargon using a mental model a smart non-specialist can follow.
- Speak like a person, not a press release or verification report.
- Never fabricate personal experience.
- Stop when the story has paid off.

Versioned prompts should contain original few-shot examples written for this
project. They should not include copied creator transcripts.

Example of the intended direction:

    Weak:
    Sqlsure is a groundbreaking and indispensable tool that could reshape
    database development.

    Stronger:
    SQL bugs have a talent for introducing themselves in production, which is
    rude. Sqlsure wants to catch them earlier. The project says its check adds
    about a tenth of a millisecond, and in one test it found 45 problems across
    2,568 queries without a false alarm. Think of it as spell-check for a
    database query: promising, fast, and still not a magic force field.

The stronger example uses selected facts, a relatable problem, a small joke,
an analogy, and a naturally stated limitation. It does not read the article or
list every available metric.

### 9.7 Channel voice configuration

Add a config block such as:

    script_generation:
      channel_voice:
        persona: curious technical friend with a skeptical eyebrow
        worldview:
          - optimistic about useful progress
          - skeptical of marketing
          - practical consequences over abstract importance
        energy: energetic but not frantic
        opinion:
          allow_first_person_editorial_opinion: true
          forbid_fabricated_personal_experience: true
        humor:
          enabled: true
          modes:
            - observational
            - dry
            - self_aware
            - absurd_analogy
          density: restrained
          allow_callbacks: true
          avoid:
            - forced meme references
            - cruelty
            - unsupported accusations
        language:
          prefer:
            - concrete verbs
            - varied sentence length
            - plain-language mental models
          avoid:
            - corporate press-release language
            - generic importance claims
            - article-summary transitions

The prompt receives this resolved block from the frozen run profile. Apps do
not read YAML directly.

### 9.8 Optional channel memory

To develop a recognizable voice over time, later add a small operator-approved
memory input containing:

- Recent episode theses.
- Running motifs or callbacks that are still usable.
- Recently overused jokes or phrases to avoid.
- Viewer questions worth revisiting.
- Published claims that received corrections.

This is not required for the first implementation. It must be explicit input,
not hidden global state.

## 10. Review and Revision

### 10.1 Reviewer purpose

The reviewer is a craft editor, not a compliance bot and not a mandatory
rewriter.

It evaluates:

- Does the opening create interest quickly?
- Does the story move through a clear mini-arc?
- Is the useful explanation easy to follow?
- Does the segment have a point of view?
- Is personality appropriate rather than forced?
- Are the strongest details doing narrative work?
- Does the payoff answer why the viewer should care?
- Does it sound spoken rather than written?
- Is humor helping clarity or interrupting it?
- Are claims and numbers still supported?

Accuracy is a hard boundary, but the review should focus on making a better
YouTube story.

### 10.2 Keep-or-rewrite contract

Use a provider-compatible root object:

    class ReviewIssue(BaseModel):
        code: Literal[
            "weak_hook",
            "flat_story_arc",
            "article_readout",
            "generic_language",
            "unclear_explanation",
            "missing_viewer_payoff",
            "weak_or_forced_personality",
            "poor_spoken_rhythm",
            "repetition",
            "unsupported_claim",
            "visual_mismatch",
        ]
        explanation: str
        affected_beat_ids: list[str]


    class StoryReviewOutput(BaseModel):
        rewrite_required: bool
        issues: list[ReviewIssue]
        revised_segment: StorySegmentOutput | None

Cross-field rules:

- rewrite_required=false requires issues=[] and revised_segment=null.
- rewrite_required=true requires at least one material issue and a complete
  revised segment for the same story.
- A good initial segment receives no replacement content.
- max_revision_passes remains config-driven and defaults to one.

The prompt must remove the current instruction to always generate a candidate.
It should include one keep example and one rewrite example.

### 10.3 Revision acceptance

The model's rewrite flag is necessary but not sufficient.

Code applies a candidate only when:

- The review contract is internally consistent.
- The candidate keeps the same story and valid beat structure.
- Existing support truth and source ownership remain stable, except for a
  bounded unsupported-claim repair using truth from the same story.
- Every spoken metric is linked to source text containing that exact metric.
- Metric subjects, upper bounds, and uncertainty qualifiers remain accurate.
- No new unsupported claim or stronger certainty appears.
- The candidate fixes at least one named craft issue.
- The candidate does not lose a working hook, explanation, creative device, or
  payoff.

A rejected candidate leaves the initial segment untouched and records exact
reasons.

Do not use raw fact count as the comparator. A shorter revision can be better
if it preserves the story's essential truth and improves the arc.

### 10.4 Bookends

The bookend storyteller runs after final story bodies.

It creates:

- A concise cold open that delivers the episode promise immediately.
- Short story connectors that continue over title interstitials.
- An ending that synthesizes the episode's pattern or leaves a useful question.

It should not list every headline in the intro or recap every story in the
closing. It cannot rewrite story bodies or introduce new factual claims.

## 11. Content-Driven Duration

Keep:

    duration_policy:
      mode: content_driven
      duration_is_approval_gate: false
      word_count_is_approval_gate: false
      timing_source_of_truth: voiceover

Suggested words may remain in prompts as loose orientation, but the system must
not repair, reject, or pad a script to hit them.

Acceptance asks:

- Did every selected story deliver a clear payoff?
- Was any sentence present only to add length?
- Did a weak story receive more time than its substance deserved?
- Did the episode end naturally?

The answer, not a clock, determines script quality.

## 12. Visual Storytelling Redesign

### 12.1 Visual goals, not card types

Each narration beat should have one primary visual job:

    show_it
    explain_it
    react_to_it
    compare_it
    emphasize_it
    transition

Examples:

- show_it: product demo, article, interface, real clip, photograph.
- explain_it: animation, process diagram, analogy visualization.
- react_to_it: restrained visual gag, reaction insert, ironic contrast.
- compare_it: real benchmark, before/after, capability comparison.
- emphasize_it: one short phrase, number, quote, or reveal.
- transition: story title, motif callback, visual reset.

Render kinds are implementation options under these goals. They should not
drive the story.

### 12.2 Verified asset catalog before final planning

Build a per-story asset catalog containing:

- Source article and documentation captures.
- Official product pages and UI.
- Product demonstrations and source clips.
- OpenGraph or hero images.
- Verified logos.
- Context images and B-roll that pass semantic checks.
- Paper figures and source charts.
- Existing visual assets suitable for analogies or reactions.

The planner receives real asset IDs and metadata. It should not assume a later
search will magically find an image.

If an asset is missing, the planner can request it. Discovery resolves the
request and only the affected scene is repaired or given a grounded fallback.

### 12.3 Visual planner input

Plan one story at a time using:

- Final story beats and visual goals.
- Actual voiceover/word alignment.
- Story direction and creative devices.
- Verified assets for that story.
- Source truth references when a visual contains facts.
- A small config-derived set of eligible visual treatments.

The planner may visualize an analogy or joke when it matches the narration. It
must not turn every factual beat into an article screenshot.

### 12.4 Real-world anchor per story

When available, each story should contain at least one real-world anchor:

- The actual product or interface.
- A source or documentation page.
- An official demo or clip.
- A verified photograph or logo.
- A real chart or paper figure.

This is broader than requiring one article scene. The best anchor depends on
the story.

### 12.5 Explanatory graphics

Code-generated motion should be used when it clarifies:

- A technical pipeline.
- A before/after workflow.
- A relationship among entities.
- A real comparison.
- A bottleneck or system behavior.
- An analogy established by the narration.

Do not generate a chart merely because the narration says "growth,"
"competition," or "better." Conceptual claims need conceptual visuals unless
real comparable data exists.

### 12.6 Visual humor and reactions

Add a bounded creative visual family for:

- Original visual analogies.
- Short reaction inserts.
- Comedic labels attached to a real product behavior.
- A callback motif from an earlier story.
- A brief absurd contrast that matches a spoken joke.

These visuals should be short and optional. They must not depend on unrelated
stock media or copy a creator's meme library.

### 12.7 Media relevance gates

The Tang Tan and Instagram failures occurred because visual quality could
outscore almost nonexistent semantic relevance.

Before quality ranking:

- Named-person assets require exact identity metadata or an approved override.
- Company/product assets require an exact entity match, official domain, or
  verified product/logo source.
- Generic context media must pass calibrated lexical or image-text semantic
  thresholds.
- Required concepts must be verified.
- Avoid concepts must reject the candidate.
- Perceptual duplicates must be rejected across adjacent scenes.

Only surviving candidates are ranked by composition, aspect ratio, resolution,
provider quality, provenance, and scene fit.

Use local CLIP-compatible embeddings as one relevance signal. Do not use CLIP
alone for named-person identity.

### 12.8 Numeric visuals

Charts and counters consume truth references. The LLM does not author arbitrary
values.

Rules:

- Data counters require a real metric or date.
- Bar and delta charts require comparable sourced values.
- Trend lines require real chronological observations.
- Display values are formatted by code from source values.
- Empty data payloads fail.
- Renderers never substitute placeholders such as AI, 100, 80, 0, or 1.

Without real comparable evidence, Apple versus OpenAI should use a product,
entity, strategic, or ecosystem visual rather than a fake bar chart.

### 12.9 Provider reliability

Wikimedia discovery must:

- Cache normalized queries.
- Deduplicate queries across scenes.
- Use an informative user agent.
- Limit concurrency to three or fewer requests.
- Honor Retry-After on HTTP 429 and 503.
- Use bounded exponential backoff when no header is present.
- Report retries, cooldowns, and incomplete candidate pools.

An incomplete search must not lower relevance requirements.

### 12.10 Scene splitting

Do not copy one scene payload into every slice when timing forces a split.

Each split must recompute:

- Active beat IDs.
- Narration excerpt.
- Visual goal.
- Creative device.
- Assets.
- Truth references.
- On-screen text.

If the visual cannot be split meaningfully, perform a targeted scene replan or
use a grounded fallback.

Implementation update (2026-07-14): the old stitcher copied one candidate
payload into every timing slice, which produced exact adjacent duplicates for
roughly 72 percent of the audited episode duration. The planner contract now
lists overlong audio units explicitly and requires multiple distinct semantic
sub-scenes for each one. The stitcher only assigns their authoritative audio
time. It raises instead of cloning a candidate. Adjacent identical effective
payloads are rejected before rendering.

### 12.11 Fallback order

Use:

    actual product, demo, or source
      -> verified logo or contextual media
      -> explanation or analogy graphic
      -> short active-beat kinetic emphasis

Never use an unrelated image merely to fill the screen.

## 13. Configuration Design

Proposed additions:

    script_generation:
      content_policy:
        duration_mode: content_driven
        duration_is_approval_gate: false
        word_count_is_approval_gate: false
      channel_voice:
        persona: curious technical friend with a skeptical eyebrow
        energy: energetic but not frantic
        opinion:
          allow_first_person_editorial_opinion: true
          forbid_fabricated_personal_experience: true
        humor:
          enabled: true
          density: restrained
          modes:
            - observational
            - dry
            - self_aware
            - absurd_analogy
      storytelling:
        require_story_engine: true
        require_viewer_payoff: true
        allow_optional_truth_details: true
        forbid_source_order_summary: true
      context_enrichment:
        enabled: false
        roles:
          - lead
          - major
        max_additional_sources_per_story: 2
      review:
        enabled: true
        mode: semantic_gate
        max_revision_passes: 1
        require_material_issue_for_rewrite: true

    visuals:
      planner:
        plan_story_by_story: true
        real_world_anchor_when_available: true
        allow_visual_analogy: true
        allow_visual_humor: true
        reject_ungrounded_numeric_scenes: true
        reject_unverified_asset_ids: true
      asset_catalog:
        build_before_final_planning: true
        source_capture_enabled: true
        product_surface_capture_enabled: true
        semantic_verification_enabled: true
        cross_scene_deduplication: true

All values are frozen into run_context.json and passed to apps. Apps do not
read YAML directly.

## 14. Evaluation Design

### 14.1 Truth gate

Truth remains pass/fail:

- Selected stories only, unless context enrichment is enabled.
- Valid source/truth references for external claims.
- No fabricated numbers, quotes, personal experience, or certainty.
- No internal IDs or production language in narration.

Passing the truth gate does not mean the script is good. It means the creative
evaluation can proceed.

### 14.2 Storytelling rubric

Evaluate each story on:

- Hook: does it create a reason to keep listening?
- Story engine: is there tension, movement, or discovery?
- Clarity: can a smart non-specialist follow the mechanism?
- Selectivity: were the most useful details chosen instead of dumped?
- Personality: does the narrator have a point of view?
- Creative fit: do analogy, humor, or reaction help rather than distract?
- Spoken rhythm: does the segment sound natural aloud?
- Viewer payoff: can the viewer explain why the story matters?
- Originality: does it avoid generic AI and press-release phrasing?
- Visual potential: do the beats suggest meaningful things to show?

Use blinded pairwise comparison between prompt or model variants. Validate any
LLM judge against human labels before trusting it.

### 14.3 Article-readout detection

Add warnings for:

- High extractive phrase overlap with source text.
- Story facts presented in nearly the same order as the source.
- Repeated report-language markers such as "the article says."
- A segment with no editorial take, explanation, analogy, reaction, or viewer
  consequence.

These are warnings or reviewer triggers, not simplistic automatic failures.
Technical names and unavoidable factual phrases should not be penalized.

### 14.4 Personality evaluation

Evaluate:

- Voice consistency across stories.
- Forced joke frequency.
- Repeated joke structures.
- Fabricated first-person claims.
- Whether opinion is useful and understandable.
- Whether serious stories receive appropriate restraint.

### 14.5 Visual evaluation

For every scene, a human or calibrated multimodal judge should answer:

- Does this show or explain the active spoken idea?
- Is the asset actually the named person, company, product, or context?
- Does a number on screen exist in the source?
- Is this visual more useful than a source, product, demo, or simple analogy?
- Is text readable and brief?
- Does the sequence vary between showing, explaining, reacting, and
  emphasizing?

Metadata-only checks are insufficient. Inspect contact sheets and complete
videos with audio.

### 14.6 Post-publication learning

After publishing enough videos:

- Track first-30-second retention.
- Mark dips at story starts, explanations, jokes, sponsors, and transitions.
- Identify replayed moments.
- Compare story roles and visual treatments against retention.
- Feed approved findings into explicit channel memory and config.

Do not optimize against a generic theory forever when channel-specific viewer
behavior becomes available.

## 15. Implementation Phases

### Phase 0: Freeze benchmarks

Implementation status: complete on 2026-07-13.

The compact fixture is in `tests/fixtures/creator_voice_benchmark/`, and the
human scoring guide is `docs/build/creator_voice_storytelling_rubric.md`.

- Preserve a compact fixture from the reference run.
- Add the channel-voice config and a human storytelling rubric.
- Create baseline script evaluations for the current output.
- Add regression cases for the harmful review and visual mismatches.

Exit condition: current weaknesses are reproducible and human-scored.

### Phase 1: Story engine and creator voice

Implementation status: complete on 2026-07-13.

The native roundup app now builds app-local truth indexes, directs each story
through an explicit story engine, returns creator-led beat metadata, and emits
non-blocking article-readout diagnostics. Phase 2 builds the conditional
keep-or-rewrite reviewer and acceptance safeguards on top of that output.

- Add source_truth.py.
- Extend the director brief with story engine, tension, payoff, narrator take,
  creative opportunities, and must-communicate truth IDs.
- Extend beat contracts with beat function, support IDs, creative device, and
  visual goal.
- Rewrite director and storyteller prompts.
- Add original weak/strong few-shot examples.
- Add source-order and corporate-language diagnostics.

Exit condition: scripts sound like authored mini-stories rather than article
summaries.

### Phase 2: Conditional craft review

Historical implementation status: superseded by Phase 2.3 on 2026-07-13.

The story and bookend reviewers now use strict nullable keep-or-rewrite
contracts. A keep decision returns no candidate. A rewrite must name material
issues against review-local beat IDs, and code rejects identical candidates,
unrelated edits, lost provenance, lost protected story functions, and newly
strengthened claim language. Numeric narration is also checked against its
linked truth text so future subjects, upper bounds, and uncertainty qualifiers
cannot be silently changed. Review calls remain observable separately from the
number of revisions actually applied.

- Add the nullable keep-or-rewrite contract.
- Replace reviewer compliance framing with the storytelling rubric.
- Add keep and justified-rewrite prompt examples.
- Implement revision acceptance checks.
- Keep one maximum revision pass.

Follow-up hardening implemented on 2026-07-16:

- A reviewer rewrite is no longer accepted merely because it is structurally
  valid. A strict structured selector compares current and candidate narration
  for the diagnosed craft issue and can keep the stronger current draft.
- The selector is bounded, config-driven, and uses the existing app-local LLM
  provider. Production keeps a valid current draft when selector evaluation
  fails; it never starts another revision loop.

Exit condition: a good segment receives no replacement, and a revision cannot
remove personality or strengthen claims.

### Phase 2.1: Content-quality hardening

Historical implementation status: partially retained; deterministic prose
diagnostics were superseded by Phase 2.3 on 2026-07-13.

The fresh-run audit showed that good writing cannot be recovered only inside
the writer prompt when upstream evidence and source authority are misleading.
This phase strengthens the existing apps without adding another agent:

- Evidence prep applies profile-configured, domain-scoped article-chrome
  cleaning before truth indexing. It reports modified records and removed
  character counts instead of silently changing source text.
- Evidence prep classifies configured hosted-project domains and community
  launch title patterns as self-published/community-launch sources.
- Story mapping scores actual source relationships instead of treating every
  record delivered through a news API as independent reporting. A single
  self-published launch receives a configured authority cap and penalty, while
  a normal independent news story keeps the existing score.
- Source relationship and source name are carried into each truth item so the
  writer can attribute project claims naturally.
- Story and bookend reviewers receive deterministic craft diagnostics for
  generic hooks, press-release phrases, missing project attribution, generic
  bookends, and formulaic connector sequences. These remain advisory; only
  real provenance, metric, structure, and configured language-policy failures
  are hard gates.
- Profanity handling is an explicit channel-voice policy. The default broad
  YouTube profile avoids profanity, including direct source quotes.
- Metadata filters configured generic title frames and raw-domain tags, and
  chapters prefer the concise title-card display title rather than cutting a
  long source headline at an awkward word boundary.

Exit condition: page chrome does not become script truth, self-published
launches cannot masquerade as independent news through their collector label,
reviewers see meaningful craft warnings without being forced to rewrite, and
metadata remains specific to the completed episode.

### Phase 2.2: Claim alignment and prompt-context hardening

Historical implementation status: source cleanup/context bounding retained;
deterministic claim-alignment gates superseded by Phase 2.3 on 2026-07-13.

The first fresh production run after Phase 2.1 exposed four remaining failure
modes: an AI-token headline was misclassified as cryptocurrency, page chrome
from The Verge and TechCrunch still entered truth indexes, the same source text
was duplicated across large director/writer/reviewer prompts, and ordinary
non-numeric claims could cite a related truth ID without that truth actually
supporting the claim.

This phase keeps the same bounded story-wise architecture and fixes those
failures without adding another agent:

- Evidence prep now uses a profile-configured crypto policy that distinguishes
  language-model tokens from crypto assets and market language.
- Domain-scoped cleanup rules remove The Verge and TechCrunch bylines, related
  links, advertising blocks, and footer navigation before story mapping.
- Truth indexes prioritize article-body and transcript text over aggregator
  descriptions, remove configured chrome phrases, and collapse repeated copies
  of the same source sentence.
- Director, writer, and reviewer truth menus have separate bounded limits. Full
  selected records remain canonical input, but the reviewer no longer receives
  a duplicate full record alongside its focused support context.
- Semantic support alignment may attach the strongest matching same-story
  truth to a factual beat. It never introduces another story or source.
- Hard claim gates reject guarantee language absent from linked source text,
  dropped embedded attribution, and configured state changes such as converting
  a job posting into a completed hire or a planned capability into a current
  feature.
- Reviewer prompts receive beat-local support text and must repair blocking
  structural issues while keeping the narration conversational.
- Generic bookend detection now covers actual production phrases and connector
  shapes such as `And finally`, repeated `Let's dive`, and mechanical
  `from X to Y` bridges. Residual craft diagnostics are returned as visible
  warnings instead of disappearing from the final checks.
- LLM summaries expose prompt/completion token usage and the frozen per-stage
  truth-context limits so cost and context growth can be audited per run.

Regression coverage includes the observed Voxa guarantee, `According to Mana`
attribution, OpenAI job-posting state, Sensor Tower estimate attribution,
Claude Code token headline, generic bookends, and article-footer contamination.

Exit condition: the known fresh-run claims cannot pass as green, AI-token news
survives evidence filtering, and each LLM stage receives a bounded,
source-prioritized truth context.

### Phase 2.3: Creator-first semantic simplification

Implementation status: complete on 2026-07-13.

The generated script is creative language, so categorical quality decisions
belong to models and people rather than brittle code heuristics.

- Removed corporate-language, generic-hook, source-order, extractive-overlap,
  metric-support, qualifier, claim-strength, attribution, and claim-state code
  gates from script approval.
- Removed deterministic craft diagnostics from writer and reviewer payloads.
- Kept the conditional reviewer with a hard maximum of one pass. KEEP remains
  the default; a rewrite must name a supplied beat and actually change it.
- Gave story reviewers the assigned story records and focused beat support so
  they can judge material faithfulness and creative quality in context.
- Updated director prompts to require hook diversity and to allow genuinely
  heterogeneous roundups without a fabricated universal thesis.
- Updated story and bookend prompts to prioritize engaging mini-stories,
  creator viewpoint, clear explanation, rhythm, and payoff.
- Limited hard script checks to Pydantic structure, selected-story/source
  ownership, known IDs, canonical order, non-empty narration, spoken-output
  hygiene, bounded loops, and provenance.
- Moved roundup-title quality to the metadata LLM prompt. Code only cleans,
  deduplicates, and bounds title options.

Exit condition: a structurally valid, source-owned script cannot be rejected by
a keyword or similarity heuristic; creative quality is assessed through the
bounded LLM review and the human storytelling rubric.

Fresh-run hardening update (2026-07-14): carrying the complete article again in
every writer and reviewer prompt produced very large prompts and diluted the
story engine. Full records remain canonical app input and downstream context,
but LLM story calls now receive a focused truth menu plus a compact record
identity manifest. Writer and reviewer prompt calibration explicitly treats
generic press-release language, ignored distinctive details, and multi-purpose
overlong beats as material craft problems. Beat duration guidance remains soft;
there is no word-count or prose-keyword approval gate.

### Phase 3: Optional context enrichment

Implementation status: optional future work. Full selected story records now
reach each writer, so this is not a blocker for the active production flow.

- Add a bounded research adapter for configured story roles.
- Restrict source classes and budgets.
- Merge new context into the truth index with provenance.
- Test failure and timeout behavior.

Exit condition: thin records can gain useful background without allowing
open-ended or untraceable research.

### Phase 4: Storytelling-first visual planner

Implementation status: active asset-first foundation implemented on 2026-07-14;
creative analogy/reaction families remain future work.

- A trusted per-story asset catalog now runs before final planning. It derives
  asset briefs from canonical script beats, registers selected source pages,
  collects bounded source-owned hero/in-article images and direct page-owned
  videos when available, and records resolvable identities under stable asset
  IDs. Lazy image attributes, `srcset`, alt text, dimensions, image/video role,
  duration, and content hashes are preserved.
- Structural media cleanup rejects extreme image aspect ratios and exact or
  perceptual near-duplicates. These checks remove unusable media geometry; they
  do not make contextual relevance decisions.
- Source-page assets carry beat-specific screenshot targets derived from exact
  canonical support truth IDs. Source screenshot normalization gives those
  truth sentences priority over loose title overlap.
- Planning uses one episode direction plus bounded story-local structured calls.
- Canonical script beats, creative devices, visual goals, selected story
  records, voiceover timing, and the story-owned asset catalog reach the story
  planner without reconstructing boundaries from prose.
- Each story plan must reference at least one available real anchor by exact
  asset ID. App code verifies asset type, availability, story ownership, source
  key, and URL rather than trusting a model-generated path.
- Scene capabilities are profile-driven. Code assigns exact timing only after
  the LLM returns semantic treatments.
- Rich graphics require complete grounded payloads. Missing semantics trigger
  bounded targeted replanning, not deterministic invention.
- Native planning, manual-plan parsing, and render preflight use one shared
  render-kind payload validator. Renderer components do not carry demo facts
  or relationships that can silently appear in a production scene.
- Exact narration kinetic text and exact source proof are the only automatic
  continuity treatments for otherwise uncovered timing.
- Overlong voice units now require planner-authored distinct semantic
  sub-scenes. Deterministic timing code cannot duplicate one scene payload to
  satisfy the render cap.
- Numeric counters reject qualitative values, and script-requested logo
  identities can extend the trusted identity catalog when the resolver
  recognizes them.
- One bounded story-local visual editor now reviews complete plans against
  exact narration units and the trusted asset catalog. Its default is keep; a
  complete replacement is accepted only after the existing payload, ownership,
  source, and scene-slot validators pass. There is no generic code fallback.

- Expand planning from the currently implemented show/explain/compare/emphasize
  treatments into restrained reaction and original visual analogy treatments.
- Keep deterministic timing from voiceover alignment as those creative
  treatments are added.

Exit condition: visuals communicate the current story beat and are not
dominated by cards or proof screenshots.

### Phase 5: Media and data safety

Implementation status: trusted-source safety and fast iteration implemented;
external-media semantic verification remains an optional paid profile.

- The default production profile is `trusted_catalog_only`. It uses selected
  source pages, source-owned images/videos, and resolvable identities without
  an additional vision-model call. Unresolved external media is not selected
  by keyword score and is not replaced with generic text.
- Structured vision verification and B-roll window selection remain available
  for a deliberately enabled external-research profile. They are deferred by
  default until evaluation shows their cost improves the final video enough.
- Numeric, relational, timeline, matrix, and workflow scenes must carry
  explicit source/script-grounded payloads. Fabricated renderer/planner values
  were removed.
- Logo assets expose their actual quality class, screenshot target misses are
  visible, fallback use is budgeted, and final assembly produces a contact
  sheet for human review.
- Text identity fallbacks preserve the complete entity name and are never
  relabeled as official logos. Media fallbacks require an exact active-script
  phrase instead of generic filler copy.
- Remotion renders every scene from one stable 1920x1080 design canvas and
  scales it uniformly to the selected 16:9 preset, preventing resolution-driven
  clipping and off-center diagrams.
- Rendering now has explicit 720p preview and delivery-quality final profiles,
  scene/story-targeted rerenders, a persistent content-addressed scene cache,
  one shared Remotion bundle, and bounded persistent-browser batch workers.
  Unchanged previews restore from cache instead of paying browser and encoder
  cost again.

- Evaluate whether paid external-media vision review materially improves the
  video before enabling it in production.
- Evaluate local image-text similarity separately; structural exact and
  perceptual duplicate detection is now implemented.
- Add provider caching, Retry-After handling, and backoff.
- Make all numeric visuals consume truth references.
- Remove renderer placeholder values.
- Rebuild payloads after scene splits.

Exit condition: the Tang Tan, Instagram lightning, and fabricated chart
regressions fail before rendering.

### Phase 6: End-to-end rollout

Implementation status: a fresh run was audited on 2026-07-16 and exposed
creator-language, loudness, and catalog-variety gaps. The corresponding
prompt, mastering, caption, and trusted-media hardening is implemented; one
new coherent production run and human review remain required.

- Run the fixture and one fresh roundup.
- Compare current and redesigned scripts blindly.
- Generate voiceover, visual plans, contact sheets, and final video.
- Inspect the complete video with audio.
- Benchmark the existing models after the new prompts and contracts.
- Upgrade a model only if evals show a remaining capability limit.

Exit condition: the script and visuals pass the acceptance criteria below.

## 16. Acceptance Criteria

The redesign is ready when:

- A two-, three-, or four-minute complete episode is accepted without padding.
- Every story has a clear engine, movement, and viewer payoff.
- Narration does not follow article structure or sound like a press release.
- The writer selects useful facts rather than maximizing fact count.
- Facts and numbers remain traceable in invisible metadata.
- The narrator expresses a consistent, useful point of view.
- Analogies and humor feel appropriate rather than mandatory.
- No fabricated first-person experience appears.
- The Sqlsure regression becomes a memorable explanation using selected
  concrete details, not a metric dump or promotional claim.
- Reviewers can return keep with no replacement.
- Revisions are applied only when they improve a named craft issue.
- Story title interstitials and voiceover identities remain synchronized.
- Every story uses an appropriate real-world visual anchor when available.
- Explanatory graphics explain an active mechanism or comparison.
- Unrelated images and invented chart values cannot pass validation.
- A human reviewer rates the script as engaging and the final visuals as
  understandable while listening to the audio.

## 17. Non-Goals

- Reading articles aloud.
- Mentioning every available source fact.
- Making evidence IDs part of spoken narration.
- Treating accuracy checks as the channel's personality.
- Copying the style, jokes, or catchphrases of another creator.
- Forcing one joke, analogy, or visual type into every story.
- Restoring fixed word counts or a hard eight-minute target.
- Adding an unbounded research or review loop.
- Solving creative quality only by buying a larger model.
- Allowing the LLM to invent source URLs, assets, data, or personal experience.

## 18. Research Basis

Channel samples:

- [Fireship: Google's AI endgame is here... everything you missed at I/O 2026](https://www.youtube.com/watch?v=9OQ5vaYbGV0)
- [Fireship: 10 weird OSS projects you need right now...](https://www.youtube.com/watch?v=qPuzWFvRajk)
- [TechLinked: You Just Don't Get It](https://www.youtube.com/watch?v=znuFb4eE9nc)
- [Matt Wolfe: AI News: An INSANE Week... Here's What Matters](https://www.youtube.com/watch?v=nydHKXjwu0U)
- [Two Minute Papers: DeepSeek Just Solved AI's Billion Dollar Problem](https://www.youtube.com/watch?v=mG4SmhWyeFA)

Platform and engineering guidance:

- [YouTube content performance guidance](https://support.google.com/youtube/answer/16559650?hl=en): deliver the title and thumbnail promise quickly, build anticipation and curiosity, and experiment with storytelling and delivery.
- [YouTube audience retention guidance](https://support.google.com/youtube/answer/9314415?hl=en): measure the first 30 seconds, move compelling material earlier, and investigate dips and replayed moments.
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs): structured output can still contain semantic mistakes; improve instructions, examples, and task decomposition.
- [OpenAI Model Optimization](https://developers.openai.com/api/docs/guides/model-optimization): establish evals, include relevant context, provide clear instructions, and provide representative examples.
- [OpenAI Evaluation Best Practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices): pairwise and pass/fail judgments are more reliable than vague scores when calibrated against human labels.
- [Pydantic Union Validation](https://docs.pydantic.dev/latest/concepts/unions/): variant-specific contracts are more predictable than one universal optional-field model.
- [MediaWiki API Etiquette](https://www.mediawiki.org/wiki/API:Etiquette/en) and [Wikimedia Rate Limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits): cache and pace requests, honor Retry-After, and use bounded backoff.
- [CLIP paper](https://arxiv.org/abs/2103.00020): image-text representation matching can support semantic candidate filtering.
- [Remotion Sequence](https://www.remotion.dev/docs/sequence): deterministic frame ranges remain suitable for story-local visual timing.
