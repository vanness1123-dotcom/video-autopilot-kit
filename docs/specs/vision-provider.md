# AI Travel Reel Generator — Vision Provider Specification

**Document Version:** 1.0
**Status:** Baseline
**Component:** Vision Provider
**Related Documents:** `system-architecture.md`, `trip-manifest.md`, `media-analyzer.md`

---

## 1. Purpose

The Vision Provider converts travel photos and representative video frames into normalized semantic observations.

Its responsibility is to answer:

> What is visually present in this media, and what travel-relevant meaning can be extracted from it?

The Vision Provider does not make final editorial decisions.

It provides structured semantic signals used by:

* Scoring System
* Media Selector
* Story Director
* Reel Planner

---

## 2. Architecture Role

The Vision Provider sits between deterministic media ingestion and editorial intelligence.

```text
Media Analyzer
      ↓
Trip Manifest
      ↓
Vision Provider
      ↓
Normalized Vision Result
      ↓
Scoring System
      ↓
Media Selector
```

The provider enriches Trip Manifest media entries.

It must not directly render, select, or plan the final Reel.

---

## 3. Responsibilities

The Vision Provider may perform:

* semantic media description
* scene classification
* activity detection
* travel-category recognition
* landmark hints
* food recognition
* environment recognition
* visual mood estimation
* people-presence detection
* group/selfie detection
* visual quality observations
* subject prominence estimation
* nighttime/daytime classification
* motion/activity inference from sampled video frames

---

## 4. Non-Responsibilities

The Vision Provider must not:

* decide final selected media
* assign final selection rank
* generate the final story
* decide shot duration
* create FFmpeg commands
* invoke the renderer
* modify source media
* upload media unnecessarily
* fabricate locations without sufficient evidence

---

## 5. Provider Abstraction

Business logic must depend on a provider-neutral interface.

Conceptual interface:

```text
VisionProvider
    analyze_photo(...)
    analyze_video(...)
```

Possible implementations:

```text
OpenAI Vision Provider
Gemini Vision Provider
Local Vision Provider
Qwen-VL Provider
```

Provider-specific SDKs and response formats must remain isolated behind adapters.

---

## 6. Provider Independence

The internal project schema must not depend on:

* OpenAI response objects
* Gemini-specific fields
* vendor-specific token accounting structures
* provider SDK classes

Every provider result must be normalized into the internal Vision schema before persistence.

---

## 7. Input Contract — Photo

Photo Vision analysis receives at minimum:

```text
media_id
source path
media type = photo
```

Optional contextual input may include:

```text
capture time
orientation
GPS
trip metadata
neighboring media metadata
```

Context should improve interpretation but must not be used to fabricate unsupported observations.

---

## 8. Input Contract — Video

The initial Vision MVP should not submit entire long videos blindly.

Preferred pipeline:

```text
Video
  ↓
deterministic frame sampling
  ↓
representative frames
  ↓
Vision analysis
  ↓
normalized video semantic result
```

This improves:

* cost
* latency
* repeatability
* debugging

---

## 9. Video Frame Sampling

The exact sampling algorithm belongs to implementation, but the baseline design should support:

* first useful frame
* middle frame
* last useful frame
* periodic frames
* optional scene-change frames

Sampling should scale with video duration.

A short 3-second clip should not require the same number of samples as a 90-second clip.

---

## 10. Normalized Vision Result

A Vision result should conceptually contain:

```json
{
  "description": null,
  "tags": [],
  "objects": [],
  "scene_type": null,
  "activity": null,
  "emotion": null,
  "travel_category": null,
  "people": {},
  "landmark": {},
  "quality_observations": {},
  "confidence": {}
}
```

This is a conceptual schema.

Detailed implementation may evolve while preserving the same responsibilities.

---

## 11. Description

`description` provides a concise factual description.

Example:

```json
"description": "Night street scene with illuminated storefronts and pedestrians."
```

Descriptions should be:

* concise
* factual
* travel-relevant
* free of unsupported speculation

Avoid verbose prose.

---

## 12. Tags

Example:

```json
"tags": [
  "night",
  "street",
  "shopping",
  "city"
]
```

Tags should use a normalized controlled vocabulary where practical.

Equivalent concepts should not fragment unnecessarily.

Bad:

```text
nighttime
night-shot
night_scene
night
```

Preferred:

```text
night
```

---

## 13. Travel Category

Recommended normalized categories:

```text
arrival
transportation
landmark
food
cafe
shopping
street
nature
cityscape
nightlife
accommodation
theme_park
activity
portrait
selfie
group
detail
transition
other
```

A media item may support one primary category and optional secondary categories.

---

## 14. Scene Type

Example normalized values:

```text
indoor
outdoor
street
restaurant
cafe
airport
station
hotel
market
park
theme_park
river
mountain
beach
cityscape
unknown
```

Scene type is visual context.

It is not the same as narrative role.

---

## 15. Activity

Example:

```text
walking
eating
shopping
riding
posing
watching
performing
driving
flying
resting
unknown
```

Activity inference should remain conservative.

---

## 16. People Analysis

Vision may record limited editorially useful information.

Example:

```json
{
  "people": {
    "count": 2,
    "group_photo": false,
    "selfie": true,
    "face_visibility": "clear"
  }
}
```

The system does not require identification of real individuals.

It only needs composition-relevant signals.

---

## 17. Landmark Analysis

Conceptual result:

```json
{
  "landmark": {
    "detected": true,
    "name": "possible landmark name",
    "confidence": 0.82
  }
}
```

A landmark name must not be treated as fact when confidence is low.

Low-confidence landmark output should remain a hint.

---

## 18. Food Analysis

For food-related media, Vision may detect:

```text
food presence
dish type
table setting
restaurant context
visual appeal
```

Exact dish names should only be returned when sufficiently supported.

The Story Director does not require exact cuisine identification to classify media as a food memory.

---

## 19. Emotion / Mood

Recommended editorial mood values:

```text
energetic
joyful
calm
romantic
luxurious
playful
adventurous
nostalgic
neutral
```

Mood represents the visual feeling of the scene.

It must not claim internal psychological state of identifiable individuals.

---

## 20. Day / Night Context

Vision should support:

```text
day
golden_hour
sunset
night
indoor_unknown
```

This is especially useful for travel storytelling and Reel pacing.

---

## 21. Quality Observations

Vision may provide semantic visual-quality observations such as:

```json
{
  "quality_observations": {
    "subject_clear": true,
    "composition_strength": "high",
    "visual_clutter": "low",
    "subject_prominence": "high"
  }
}
```

These are signals.

They are not the final score.

Final weighting belongs to `scoring-system.md`.

---

## 22. Technical vs Semantic Quality

Technical measurements should preferably remain deterministic where possible.

Examples:

```text
blur
resolution
exposure histogram
duration
orientation
```

may be measured algorithmically.

Vision should focus on areas where semantic judgment adds value.

Examples:

```text
subject importance
composition appeal
travel relevance
story value
scene meaning
```

This prevents unnecessary AI cost.

---

## 23. Confidence

Important semantic claims should support confidence.

Example:

```json
{
  "confidence": {
    "scene_type": 0.96,
    "travel_category": 0.88,
    "landmark": 0.54
  }
}
```

Confidence values should be normalized to:

```text
0.0 – 1.0
```

Low-confidence claims must not be silently promoted to fact.

---

## 24. Structured Output

Whenever provider capability permits, Vision requests should require structured JSON output.

Free-form prose should not be the canonical result.

Preferred pattern:

```text
Provider Response
      ↓
Provider Adapter
      ↓
Schema Validation
      ↓
Normalized Vision Result
```

Invalid provider output must fail validation or degrade gracefully.

---

## 25. Prompt Design

Vision prompts should emphasize:

* factual observations
* concise output
* travel relevance
* structured schema
* no unsupported location guessing
* no storytelling
* no final media selection

Provider prompts should not ask:

> Should this image be included in the final Reel?

That decision belongs to Media Selector.

---

## 26. Trip Context

Vision may receive limited trip context.

Example:

```text
Trip name
Known country
Known city list
Capture date
```

This context can disambiguate observations.

However, context must not override visible evidence.

Example:

If a trip is known to be in Seoul, Vision may use Seoul as context.

It must not identify every unknown building as a Seoul landmark.

---

## 27. Batch Processing

The provider architecture should support batching where available.

Potential advantages:

* reduced request overhead
* lower latency
* lower cost

However, batch size must not:

* exceed provider limits
* reduce output reliability
* make media/result mapping ambiguous

Every result must retain the original `media_id`.

---

## 28. Caching

Vision analysis can be expensive.

Results should be reusable when:

* source media is unchanged
* Vision provider configuration is unchanged
* Vision schema version is compatible

A conceptual cache key may include:

```text
media_id
source fingerprint
provider
model
prompt/schema version
```

Changing Story logic must not invalidate Vision cache.

---

## 29. Cost Control

Vision is one of the primary variable-cost components.

Cost-control mechanisms may include:

* thumbnail resizing
* representative video frames
* batch requests
* caching
* skipping unsupported media
* deterministic pre-filtering

The system should avoid sending full-resolution source media when smaller representations provide sufficient semantic information.

---

## 30. Privacy

Vision may use cloud providers.

Therefore, the implementation must make provider behavior explicit.

Raw travel media may contain:

* faces
* children
* private locations
* GPS-associated memories
* personal environments

Requirements:

* do not upload media from Analyzer automatically
* cloud Vision must occur only in Vision Provider
* provider credentials must remain outside Git
* local Vision should remain architecturally possible

---

## 31. Error Handling

Possible errors include:

```text
VisionProviderUnavailable
VisionAuthenticationError
VisionRateLimitError
VisionTimeoutError
VisionResponseValidationError
VisionMediaUnsupportedError
```

Failure of one media item should not automatically invalidate all completed Vision results.

---

## 32. Retry Strategy

Transient errors may support bounded retries.

Examples:

```text
timeout
rate limit
temporary provider failure
```

Retries must be:

* limited
* logged
* idempotent where possible

Permanent schema errors should not be retried indefinitely.

---

## 33. Provider Metadata

For reproducibility, the system should preserve limited processing metadata.

Example:

```json
{
  "vision_metadata": {
    "provider": "provider-name",
    "model": "model-name",
    "schema_version": "1.0",
    "analyzed_at": "..."
  }
}
```

Do not persist credentials.

---

## 34. Photo Processing Strategy

Recommended MVP flow:

```text
Photo
 ↓
optional resize
 ↓
Vision Provider
 ↓
Normalize result
 ↓
Validate
 ↓
Persist to Trip Manifest
```

The original file remains unchanged.

---

## 35. Video Processing Strategy

Recommended MVP flow:

```text
Video
 ↓
FFprobe metadata
 ↓
representative frame extraction
 ↓
Vision Provider
 ↓
aggregate frame observations
 ↓
normalized video result
 ↓
Trip Manifest
```

Audio understanding is not required for the Vision MVP.

---

## 36. Frame Aggregation

For videos, frame-level observations must be combined carefully.

Example:

Frame 1:

```text
train station
```

Frame 2:

```text
train interior
```

Frame 3:

```text
moving city view
```

Normalized video interpretation may become:

```text
travel_category = transportation
activity = riding
scene_type = station/train
```

The exact aggregation algorithm belongs to implementation.

---

## 37. Vision Output Ownership

Vision Provider may write fields such as:

```text
description
tags
objects
emotion
scene_type
travel_category
people
landmark
quality_observations
vision_metadata
```

It must not write:

```text
selected
selection_rank
final_score
story order
shot duration
render commands
```

---

## 38. Manifest Integration

Vision results should enrich media objects rather than create disconnected duplicate records.

Conceptually:

```json
{
  "id": "photo-abc123",
  "path": "Photos/IMG_1001.jpg",
  "description": "...",
  "tags": [],
  "objects": [],
  "emotion": null
}
```

Media identity must remain unchanged before and after Vision.

---

## 39. Validation Requirements

Vision output validation should verify:

* result belongs to expected media ID
* required schema shape exists
* confidence values fall within valid range
* controlled-vocabulary fields are valid
* no unexpected provider-native objects leak through
* JSON is serializable

Invalid optional fields may degrade to `null` where safe.

---

## 40. Testing Strategy

Automated tests should cover:

* provider interface contract
* normalization
* malformed provider output
* missing fields
* confidence validation
* provider exception handling
* photo result mapping
* video frame-result aggregation
* cache behavior
* manifest enrichment

Unit tests should mock cloud APIs.

CI must not require paid AI requests.

---

## 41. Provider Selection

Provider selection should eventually be configuration-driven.

Example:

```yaml
vision:
  provider: openai
  model: example-model
```

Core logic should not contain provider names in editorial modules.

---

## 42. Local Provider Strategy

Local Vision support is desirable for:

* privacy
* offline experimentation
* cost control
* provider independence

The architecture must therefore avoid assumptions that every Vision provider:

* accepts URLs
* has cloud authentication
* uses the same image encoding
* supports the same structured-output mechanism

Adapters handle these differences.

---

## 43. MVP Scope

The Vision MVP needs to achieve only enough semantic understanding to support good travel Reel selection.

Required:

* description
* tags
* travel category
* scene type
* people/selfie hints
* mood
* semantic-quality observations

Optional for later:

* precise landmark recognition
* OCR
* detailed food identification
* facial-expression scoring
* advanced video action recognition

---

## 44. Quality Gates

A Vision Provider implementation must not be approved if it:

1. couples editorial modules directly to one AI vendor
2. writes final selection decisions
3. performs rendering
4. stores raw provider SDK objects in Trip Manifest
5. fabricates location facts
6. submits every full video without sampling controls
7. lacks structured-output validation
8. has no failure isolation
9. stores API credentials in project files
10. forces Vision to rerun when only downstream Story logic changes

---

## 45. Baseline Decision

Vision is a semantic observation layer.

Its contract is:

> Observe and describe the travel media in a normalized, provider-independent form.

It does not decide what the user should publish.

That responsibility begins in the Scoring and Selection layers.
