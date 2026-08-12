# AI Travel Reel Generator — Scoring System Specification

**Document Version:** 1.0
**Status:** Baseline
**Component:** Scoring System
**Related Documents:** `system-architecture.md`, `trip-manifest.md`, `media-analyzer.md`, `vision-provider.md`

---

## 1. Purpose

The Scoring System converts deterministic media facts and normalized Vision observations into explainable editorial scores.

Its purpose is to answer:

> How useful is this photo or video as source material for a short travel Reel?

The Scoring System does not make the final selection by itself.

It produces structured signals consumed by the Media Selector.

---

## 2. Design Principle

The scoring model must be hybrid.

It combines:

1. deterministic technical signals
2. Vision-derived semantic signals
3. travel-editorial signals
4. penalties for redundancy or poor suitability

The system must not rely on a single opaque LLM score.

---

## 3. Output Contract

For backward compatibility with Sprint 2:

```json
"score": 0.87
```

remains the normalized total score.

Detailed scoring is stored separately:

```json
"score_breakdown": {
  "technical": 0.90,
  "composition": 0.82,
  "travel_relevance": 0.95,
  "story_value": 0.91,
  "uniqueness": 0.76,
  "emotion": 0.84,
  "vertical_suitability": 0.88,
  "penalties": {
    "duplicate": 0.10,
    "blur": 0.00,
    "low_information": 0.00
  }
}
```

All normalized component scores use:

```text
0.0 – 1.0
```

unless explicitly documented otherwise.

---

## 4. Scoring Objectives

The system should favor media that is:

* technically usable
* visually strong
* travel-relevant
* story-supportive
* emotionally engaging
* distinctive
* representative of the trip
* suitable for short-form vertical editing

It should penalize media that is:

* blurred
* badly exposed
* near-duplicate
* visually empty
* low-information
* repetitive
* difficult to crop for vertical output
* redundant within the same scene

---

## 5. Score Categories

V1 defines the following major categories:

```text
Technical Quality
Composition
Travel Relevance
Story Value
Uniqueness
Emotion / Human Interest
Vertical Suitability
Penalty Layer
```

These categories are intentionally separate.

---

## 6. Technical Quality

Technical Quality measures whether media is usable.

Possible deterministic signals include:

* sharpness
* resolution
* exposure
* clipping
* video stability
* video duration
* codec readability
* frame corruption

Example conceptual score:

```text
technical = 0.0 – 1.0
```

Technical Quality should rely on deterministic measurement where practical.

---

## 7. Sharpness

Sharpness should preferably be measured algorithmically.

Possible techniques:

* Laplacian variance
* edge density
* motion blur estimation

Vision may provide a semantic blur observation, but deterministic measurement should remain primary.

Severely blurred media may trigger a penalty or hard rejection.

---

## 8. Exposure

Exposure quality may consider:

* extreme underexposure
* extreme overexposure
* highlight clipping
* shadow clipping

The system should avoid penalizing intentional night photography simply because the image is dark.

Context matters.

---

## 9. Composition

Composition represents semantic visual quality.

Signals may include:

* clear subject
* subject prominence
* framing
* visual balance
* clutter
* depth
* leading lines
* strong foreground/background relation

This category is expected to rely substantially on Vision observations.

---

## 10. Travel Relevance

Travel Relevance measures whether the media contributes to the travel experience.

Examples of high relevance:

* recognizable destination
* transportation
* street scenes
* landmarks
* local food
* markets
* hotel arrival
* theme park
* city atmosphere
* scenic views
* local cultural details

Examples of lower relevance:

* generic screenshots
* accidental pocket photos
* unrelated objects
* repeated close-ups with no context

---

## 11. Story Value

Story Value measures whether a media item helps explain the journey.

A technically perfect photo may still have low story value.

Examples:

High Story Value:

```text
airport departure
arrival scene
first meal
major landmark
transition between districts
night ending
```

Low Story Value:

```text
sixth nearly identical shop photo
generic wall
random object without context
```

Story Value is not identical to visual quality.

---

## 12. Uniqueness

Uniqueness measures whether the media contributes something not already represented.

High uniqueness:

* one-of-a-kind event
* unusual view
* distinctive activity
* unique environment

Low uniqueness:

* repeated selfie pose
* burst sequence
* same landmark from almost identical angle

Uniqueness must be evaluated relative to the trip, not in isolation.

---

## 13. Emotion / Human Interest

Emotion measures editorial engagement.

Potential positive signals:

* joy
* interaction
* excitement
* surprise
* movement
* memorable expressions
* human connection

The system must not infer sensitive psychological traits.

It only evaluates visible editorial energy.

---

## 14. Vertical Suitability

Because the target is 9:16, media should receive a suitability signal.

Possible factors:

* native portrait orientation
* centered subject
* safe crop region
* subject survives vertical crop
* sufficient resolution for crop
* landscape scene can support blur-fill or pan/zoom

Landscape media must not be automatically rejected.

Existing rendering capabilities may adapt it.

---

## 15. Photo vs Video Scoring

Photos and videos share some categories but require different treatment.

### Photos

Important dimensions:

* sharpness
* composition
* expression
* travel relevance
* uniqueness
* crop suitability

### Videos

Important dimensions:

* stability
* usable duration
* motion
* action
* subject continuity
* visual quality
* scene information
* vertical suitability

A static video with no meaningful movement may score lower than a strong still image.

---

## 16. Video Motion Value

Video-specific scoring should consider whether motion adds editorial value.

Positive examples:

* walking
* transportation movement
* rides
* food preparation
* waves
* street movement
* performances

Low-value examples:

* camera pointed at a static wall
* long idle recording
* severe shake
* accidental recording

---

## 17. Penalty Layer

Penalties reduce total score.

Recommended V1 penalties:

```text
duplicate_penalty
blur_penalty
exposure_penalty
low_information_penalty
crop_penalty
instability_penalty
```

Penalties should remain inspectable.

---

## 18. Duplicate Penalty

Duplicate handling is essential.

The system should distinguish:

### Exact duplicate

Same file or exact content.

### Near duplicate

Visually almost identical.

Examples:

* burst photos
* repeated selfies
* same landmark angle

Near duplicates should not all survive selection.

---

## 19. Duplicate Detection Strategy

A hybrid strategy is recommended:

```text
deterministic similarity
+
perceptual hash
+
Vision semantic similarity
```

Potential methods:

* pHash
* dHash
* embedding similarity
* capture-time proximity
* Vision tag similarity

Exact algorithm belongs to implementation.

---

## 20. Scene-Level Diversity

Scoring must not optimize only global top score.

Example failure:

```text
Top 20 media = all Lotte World photos
```

even if they are individually excellent.

The Selector will apply diversity constraints, but Scoring should expose enough information to support scene balance.

---

## 21. Initial V1 Weighting

Recommended starting weights:

| Category                 | Weight |
| ------------------------ | -----: |
| Technical Quality        |   0.15 |
| Composition              |   0.15 |
| Travel Relevance         |   0.20 |
| Story Value              |   0.20 |
| Uniqueness               |   0.10 |
| Emotion / Human Interest |   0.10 |
| Vertical Suitability     |   0.10 |

Total:

```text
1.00
```

This is a baseline, not a permanent truth.

Weights should be configuration-driven.

---

## 22. Total Score Formula

Conceptually:

```text
base_score =
    technical * 0.15
  + composition * 0.15
  + travel_relevance * 0.20
  + story_value * 0.20
  + uniqueness * 0.10
  + emotion * 0.10
  + vertical_suitability * 0.10
```

Then:

```text
final_score = clamp(base_score - penalties, 0.0, 1.0)
```

The exact implementation may evolve.

---

## 23. Why Story and Travel Receive Higher Weight

The goal is not to create a photography contest.

The goal is to create a travel Reel.

Therefore:

```text
Travel Relevance
+
Story Value
```

must matter more than pure technical perfection.

A slightly imperfect but memorable travel moment may be more valuable than a technically perfect generic image.

---

## 24. Hard Rejection

Some media may be rejected before ranking.

Possible hard-reject conditions:

* unreadable file
* corrupted media
* extreme blur
* zero usable video frames
* invalid duration
* exact duplicate of an already indexed file

Hard rejection must include a reason.

---

## 25. Soft Rejection

Other media should remain in the manifest but rank poorly.

Examples:

* weak composition
* redundant scene
* low travel relevance
* difficult crop
* repetitive content

This allows later manual inspection.

---

## 26. Selection Explainability

Each media item should eventually support a concise explanation.

Example:

```json
{
  "score": 0.91,
  "score_reason": [
    "strong travel relevance",
    "clear subject",
    "unique night scene",
    "good vertical crop"
  ]
}
```

The explanation is not hidden chain-of-thought.

It is a structured editorial rationale.

---

## 27. Score Breakdown Ownership

The Scoring System owns:

```text
score
score_breakdown
score_reason
```

The Vision Provider owns semantic observations.

The Selector owns:

```text
selected
selection_rank
selection_reason
```

These responsibilities must remain separate.

---

## 28. Missing Data

Missing Vision or metadata must not automatically cause failure.

Example:

```text
GPS unavailable
```

should not reduce image quality score.

The scoring system should distinguish:

```text
unknown
```

from:

```text
bad
```

Missing evidence is not negative evidence.

---

## 29. Confidence-Aware Scoring

Low-confidence Vision observations should have reduced influence.

Example:

```text
landmark confidence = 0.35
```

must not contribute the same travel relevance bonus as:

```text
landmark confidence = 0.98
```

---

## 30. Configurability

Weights must eventually be configurable.

Example:

```yaml
scoring:
  technical: 0.15
  composition: 0.15
  travel_relevance: 0.20
  story_value: 0.20
  uniqueness: 0.10
  emotion: 0.10
  vertical_suitability: 0.10
```

Configuration validation must ensure total weighting remains valid.

---

## 31. Style-Aware Scoring

V1 scoring should remain primarily style-neutral.

Future versions may apply style profiles.

Example:

```text
cinematic
vlog
luxury
cute
```

A cinematic profile may favor:

* landscapes
* lighting
* atmosphere

A vlog profile may favor:

* people
* action
* interaction

Style-specific scoring is post-MVP unless required by product validation.

---

## 32. Temporal Context

Capture time can improve scoring.

Examples:

* beginning of trip
* first arrival
* sunset
* final night
* departure

Temporal context should influence Story Value, not Technical Quality.

---

## 33. GPS / Location Context

GPS may help identify scene diversity.

However:

* GPS absence must not penalize media
* GPS itself is not a quality signal

Location context is useful for:

```text
travel_relevance
uniqueness
scene diversity
```

---

## 34. Scoring Pipeline

Recommended sequence:

```text
Media Analyzer facts
        +
Vision observations
        ↓
Technical signals
        ↓
Semantic/editorial signals
        ↓
Penalty calculation
        ↓
Score breakdown
        ↓
Normalized score
        ↓
Trip Manifest
```

---

## 35. Idempotency

Given:

* same media
* same metadata
* same Vision result
* same scoring configuration
* same scoring version

the score should be reproducible.

Randomness should not affect baseline scoring.

---

## 36. Scoring Version

Future implementation should preserve:

```text
scoring_version
```

Example:

```json
{
  "scoring_version": "1.0"
}
```

This is important because changing weights or formulas changes meaning.

---

## 37. Regression Testing

A fixed test fixture set should eventually validate that scoring changes do not create unexpected ranking shifts.

Example:

```text
good landmark > accidental blur
unique activity > duplicate burst
usable video > unstable accidental clip
```

Tests should focus on relative ranking as well as numeric values.

---

## 38. Real-World Validation

The scoring system must be tested on full travel collections.

A useful validation question is:

> Do the top-ranked media approximately match what a human would consider memorable and publishable?

Metrics may include:

* human top-N overlap
* duplicate rate
* scene coverage
* photo/video balance

---

## 39. Human Override

Future versions may support:

```text
favorite
force_include
force_exclude
```

Human override should supersede automatic ranking.

This is not required for the initial MVP.

---

## 40. Failure Modes

Common scoring failures include:

### Photography bias

System selects only technically perfect images.

### Selfie bias

System over-selects faces.

### Landmark bias

System selects too many landmarks.

### Recency bias

System favors later media.

### Duplicate saturation

Many similar images dominate.

### Video starvation

Photos consistently outrank usable videos.

The Selector specification must mitigate these risks.

---

## 41. Performance

Deterministic quality calculations should be lightweight.

Vision should not be rerun during scoring unless required data is missing.

The Scoring System consumes previously persisted Vision results.

---

## 42. Privacy

Scoring should occur locally after Vision results are available.

No additional cloud request should be required solely to calculate the numeric score unless explicitly justified.

---

## 43. Testing Requirements

Automated tests should cover:

* score normalization
* weighting
* penalty application
* missing values
* hard rejection
* duplicate penalty
* confidence weighting
* photo scoring
* video scoring
* reproducibility
* score breakdown serialization

---

## 44. Quality Gates

A scoring implementation must not be approved if it:

1. produces only an unexplained LLM score
2. changes score meaning without versioning
3. treats missing GPS as poor quality
4. allows duplicate media to dominate
5. ignores photo/video differences
6. couples scoring directly to a cloud provider
7. mixes selection state into scoring responsibility
8. produces values outside the normalized range
9. cannot explain major penalties
10. requires Vision reruns for every scoring change

---

## 45. Baseline Decision

The Scoring System is an explainable ranking layer.

Its contract is:

> Convert technical facts and semantic travel observations into stable editorial signals that help the Selector choose the best and most representative memories.

A high score means:

> This media is strong source material.

It does not mean:

> This media must appear in the final Reel.
