# Creator Voice Storytelling Rubric

Use this rubric for blinded human pairwise review of roundup story segments.
Machine-verifiable contract and provenance checks happen first. Creative and
semantic quality are assessed here, not converted into deterministic code
scores.

Score every dimension from 1 to 5. Read the narration aloud before scoring
spoken rhythm. Reviewers should not know which prompt or model produced a
candidate.

| Dimension | 1 | 3 | 5 |
| --- | --- | --- | --- |
| Hook | Generic introduction with no reason to continue | Establishes the topic and some curiosity | Creates immediate tension, surprise, consequence, or a compelling question |
| Story engine | Facts sit beside each other | Some movement exists but the middle is flat | Clear setup, development, and satisfying reveal or payoff |
| Clarity | Jargon or relationships are hard to follow | Main idea is understandable | A smart non-specialist can explain the mechanism afterward |
| Selectivity | Dumps available facts and metrics | Chooses some useful details | A few strong facts do specific narrative work |
| Personality | Sounds like a press release or newswire | Occasional viewpoint appears | Consistent, useful narrator perspective without manufactured certainty |
| Creative fit | No creative device, or forced jokes distract | One useful analogy, reaction, or contrast | Creativity improves understanding and feels native to the story |
| Spoken rhythm | Dense written prose or repetitive cadence | Mostly natural speech | Varied, concise, and enjoyable when read aloud |
| Viewer payoff | Ends after reporting what happened | States a generic consequence | Resolves why the viewer should care or how interpretation changes |
| Originality | Generic AI language and interchangeable claims | Some specific wording | Distinct framing and language without imitating another creator |
| Visual potential | Beats imply walls of text | Some concrete scenes are possible | Each major beat suggests meaningful proof, explanation, comparison, or reaction visuals |

## Editorial Preflight

Before creative scoring, a human reviewer should sanity-check:

- The segment remains materially faithful to the selected story records.
- Opinion, analogy, humor, and hypotheticals are recognizable as creator framing.
- The script does not fabricate personal experience.
- Internal IDs and production directions are absent from narration.

This preflight is editorial judgment. The runtime only verifies known IDs,
source ownership, canonical structure, and other objective integrity rules.

## Review Method

1. Randomize candidate order and hide model/prompt names.
2. Score each story independently, then score episode continuity separately.
3. Record one concrete reason for every score of 1, 2, 4, or 5.
4. Prefer pairwise judgments such as "A has the clearer payoff" over vague overall impressions.
5. Treat humor as optional. A restrained serious segment can score 5 when humor would be inappropriate.
6. Keep operator notes with the benchmark output; do not convert this rubric into a mandatory LLM rewrite loop.

The deterministic fixture lives in
`tests/fixtures/creator_voice_benchmark/`. Its reference scores calibrate the
current known weak/strong examples but do not replace human review of new
scripts.
