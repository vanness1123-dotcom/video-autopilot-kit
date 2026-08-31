# AI Travel Reel Generator — Reel Planner Specification

**Document Version:** 1.0

> Sprint 7.5 Planner reduction preserves Event representatives and block order. Plans expose `event_id`, `scene_role`, `event_switch_count`, and `event_fragmentation_count`; an explicitly marked opening teaser is exempt from fragmentation.
**Status:** Baseline
**Component:** Reel Planner
**Related Documents:** `system-architecture.md`, `trip-manifest.md`, `media-selector.md`, `story-engine.md`, `renderer.md`

---

## 1. Purpose

The Reel Planner converts a structured travel story into a deterministic editorial execution plan.

Its responsibility is to answer:

> Which media appears, in what order, for how long, and with what editing intent?

The Reel Planner is the final decision layer before rendering.

It does not execute FFmpeg.

---

## 2. Architecture Role

```text
Media Selector
      ↓
Story Engine
      ↓
Reel Planner
      ↓
reel_plan.json
      ↓
Rendering Adapter
      ↓
Rendering Engine
```

The Planner translates narrative intent into an inspectable timeline contract.

---

## 3. Responsibilities

The Reel Planner is responsible for:

* final shot selection from candidate media
* shot ordering
* target duration allocation
* photo display duration
* video in/out selection
* scene timing
* transition intent
* text-overlay timing intent
* pacing
* photo motion intent
* BGM timing intent
* total-duration validation
* generation of `reel_plan.json`

---

## 4. Non-Responsibilities

The Reel Planner must not:

* scan source folders
* perform Vision analysis
* calculate media quality from raw files
* regenerate Story Engine output
* encode video
* invoke FFmpeg directly
* modify source media
* perform final QA

---

## 5. Target Output

V1 target:

```text
Duration: approximately 40 seconds
Aspect ratio: 9:16
Resolution: 1080 × 1920
Format: MP4
```

Planner duration must remain within a configured tolerance.

Recommended initial tolerance:

```text
38–42 seconds
```

The exact final render may differ slightly due to transition implementation or encoder timing.

---

## 6. Reel Plan

The primary Planner output is:

```text
reel_plan.json
```

It is the rendering-independent editorial contract between:

```text
AI/editorial pipeline
```

and:

```text
Rendering Adapter
```

---

## 7. Conceptual Reel Plan Schema

```json
{
  "plan_version": "1.0",
  "trip_id": "Korea2026",
  "target_duration_seconds": 40.0,
  "aspect_ratio": "9:16",
  "resolution": {
    "width": 1080,
    "height": 1920
  },
  "fps": 30,
  "shots": [],
  "transitions": [],
  "text_overlays": [],
  "audio": {},
  "validation": {}
}
```

The exact implementation may evolve while preserving the contract.

---

## 8. Shot

Every final Reel element is represented as a Shot.

Conceptual structure:

```json
{
  "shot_id": "shot-001",
  "media_id": "video-abc123",
  "scene_id": "scene-001",
  "role": "hook",
  "media_type": "video",
  "timeline_start": 0.0,
  "duration": 2.4,
  "source_in": 3.2,
  "source_out": 5.6,
  "motion": null,
  "crop_intent": "center",
  "priority": 1.0
}
```

---

## 9. Shot Identity

Each shot must have a stable unique ID within a Reel Plan.

Example:

```text
shot-001
shot-002
shot-003
```

Shot identity is separate from media identity.

The same media ID should normally map to only one shot in V1.

---

## 10. Photo Shot

Photo shots require:

```text
media_id
duration
crop intent
motion intent
```

Possible motion intents:

```text
static
zoom_in
zoom_out
pan_left
pan_right
pan_up
pan_down
ken_burns
```

The Planner expresses intent.

The renderer determines the exact FFmpeg filter implementation.

---

## 11. Video Shot

Video shots require:

```text
media_id
source_in
source_out
duration
```

Source duration must be valid.

Conceptual rule:

```text
source_out - source_in = requested source segment
```

The renderer may adjust marginally for codec/frame boundaries.

---

## 12. Video Segment Selection

The Planner should prefer the most useful section of a video rather than always starting at second zero.

Potential inputs:

* Vision frame analysis
* motion value
* scene-change hints
* available duration
* story role

For MVP, segment selection may remain relatively simple and deterministic.

---

## 13. Shot Count

For approximately 40 seconds, recommended V1 target:

```text
15–25 shots
```

Typical average duration:

```text
1.5–3.0 seconds per shot
```

This is not a hard rule.

Hero scenes may remain longer.

Details may be much shorter.

---

## 14. Pacing Model

Recommended normalized pacing profiles:

```text
slow
moderate
fast
dynamic
```

Approximate interpretation:

### Slow

```text
3–5 seconds per shot
```

### Moderate

```text
2–3 seconds
```

### Fast

```text
1–2 seconds
```

### Dynamic

Variable durations based on content and music.

MVP default:

```text
dynamic travel
```

with moderate overall rhythm.

---

## 15. Duration Allocation

Duration should reflect:

```text
story priority
media strength
motion value
scene importance
visual complexity
narrative role
```

Duration must not simply be:

```text
40 seconds / number of shots
```

---

## 16. Narrative Duration

Conceptual 40-second allocation:

| Section                | Approximate Duration |
| ---------------------- | -------------------: |
| Hook                   |                2–4 s |
| Arrival / Establishing |                4–6 s |
| Exploration            |               8–10 s |
| Experiences            |               8–10 s |
| Highlight              |               8–10 s |
| Closing                |                3–5 s |

These are planning guidelines only.

The Planner adapts to actual Story Engine output.

---

## 17. Hook Timing

The Hook should usually occur immediately.

Recommended:

```text
0.0–3.0 seconds
```

A weak slow intro should be avoided unless explicitly required by style.

---

## 18. Hero Shot Duration

Hero shots may receive more screen time.

Typical:

```text
2.5–4.0 seconds
```

depending on motion and visual complexity.

---

## 19. Detail Shot Duration

Detail shots may be short:

```text
0.8–1.8 seconds
```

Examples:

* food detail
* signage
* souvenir
* coffee
* ticket

---

## 20. Transition Shots

Motion-oriented transition media may use:

```text
0.8–2.0 seconds
```

Examples:

* train window
* walking
* escalator
* street movement

---

## 21. Scene Duration

The Planner should allocate duration by scene priority.

Conceptually:

```text
scene_weight =
story_priority
× available_good_media
× narrative_need
```

Exact formula belongs to implementation.

---

## 22. Timeline Continuity

Shots must form a continuous timeline.

Required:

```text
shot_1 end = shot_2 start
```

after accounting for transition overlap.

Timeline gaps are invalid unless intentionally defined.

---

## 23. Transition Intent

Recommended transition types:

```text
cut
crossfade
fade
dip_to_black
match_motion
```

MVP should prefer restraint.

Recommended default:

```text
cut
```

with selective:

```text
crossfade
```

or:

```text
fade
```

Too many visual transitions reduce professionalism.

---

## 24. Transition Ownership

Planner decides:

```text
transition intent
transition location
approximate duration
```

Renderer decides:

```text
FFmpeg filter
exact frame timing
technical implementation
```

---

## 25. Transition Duration

Recommended starting ranges:

```text
cut           = 0
crossfade     = 0.2–0.6 s
fade          = 0.3–0.8 s
dip_to_black  = 0.3–0.8 s
```

Transition duration must not unexpectedly push final Reel beyond tolerance.

---

## 26. Photo Motion

Photos require motion or framing strategy to prevent slideshow-like output.

Recommended V1 policy:

```text
portrait photo → subtle zoom/pan
landscape photo → crop or blur-fill + subtle motion
detail photo → subtle zoom
hero photo → slower Ken Burns
```

Motion should remain restrained.

---

## 27. Motion Repetition

Avoid:

```text
zoom_in
zoom_in
zoom_in
zoom_in
```

across consecutive photos.

Planner should vary motion intentionally.

---

## 28. Crop Intent

Planner may describe crop strategy:

```text
center
subject_centered
top_safe
bottom_safe
face_safe
blur_fill
fit
```

Renderer performs actual crop computation.

---

## 29. Vertical Output

The target output is 9:16.

Planner should consider:

* original orientation
* subject location
* cropping risk
* existing blur-fill capability
* visual consistency

Landscape media must remain usable when editorially valuable.

---

## 30. Text Overlay

Planner converts Story Engine overlay intent into timeline placement.

Conceptual structure:

```json
{
  "id": "text-001",
  "text": "SEOUL",
  "start": 0.4,
  "duration": 1.8,
  "style": "title"
}
```

---

## 31. Overlay Types

Recommended baseline:

```text
title
location
day
scene
closing
```

MVP should not overuse text.

---

## 32. Text Safe Area

Planner should assume mobile UI obstruction.

Text placement must respect configurable safe areas.

Renderer is responsible for exact positioning.

---

## 33. Subtitles

Narration subtitles are not required for V1 unless narration is introduced.

Text overlays and subtitles must remain conceptually distinct.

Existing subtitle rendering capabilities may be reused later.

---

## 34. Audio Intent

The Planner may describe:

```text
BGM file/reference
music start
music section
fade in/out
energy profile
```

Actual audio processing belongs to renderer.

---

## 35. BGM Requirement

V1 should support one background music track when provided or configured.

Automatic generative music is outside MVP.

---

## 36. Beat Awareness

Future Planner versions may align cuts to beats.

MVP does not require full beat-synchronous editing.

Existing BGM highlight or segment-selection functionality should be reused where appropriate.

---

## 37. Audio Narrative Arc

Conceptual music-energy alignment:

```text
Hook → immediate interest
Exploration → build
Highlight → strongest section
Closing → release / fade
```

Planner may express this as intent.

---

## 38. Story Preservation

Planner must preserve Story Engine scene order unless there is a documented technical reason to adjust.

It must not independently rewrite the narrative.

---

## 39. Candidate Substitution

If a planned media item becomes unusable, Planner may support fallback candidates.

Conceptually:

```json
{
  "media_id": "photo-A",
  "fallback_media_ids": [
    "photo-B",
    "photo-C"
  ]
}
```

This is optional for MVP but valuable for resilience.

---

## 40. Selected vs Planned

Media Selector:

```text
selected = candidate pool
```

Reel Planner:

```text
planned = actual final shot
```

Not every selected candidate must appear in final Reel.

This distinction is mandatory.

---

## 41. Final Shot Decision

Planner should normally choose:

```text
15–25 shots
```

from a candidate pool that may contain:

```text
40–70 media items
```

This provides editorial flexibility.

---

## 42. Scene Coverage Validation

Planner should verify that important Story Engine scenes are represented.

A high-priority scene must not accidentally receive zero shots.

---

## 43. Duplicate Validation

Near-duplicate shots should generally not appear adjacent.

Exact duplicate media reuse is prohibited in V1.

---

## 44. Media Mix Validation

Planner should inspect:

```text
photo count
video count
```

but should not enforce a rigid ratio when source quality does not support it.

---

## 45. Duration Budget

Every Reel Plan has a duration budget.

Conceptually:

```text
target = 40.0 seconds
```

Planner must account for:

```text
shots
transition overlap
opening/closing fades
```

before approving plan.

---

## 46. Duration Tolerance

Recommended:

```text
minimum = 38 s
maximum = 42 s
```

Configurable.

Plans outside tolerance should fail validation or trigger automatic adjustment.

---

## 47. Automatic Duration Adjustment

Potential strategy:

```text
too long
 ↓
shorten low-priority shots
 ↓
remove lowest-priority detail shot
 ↓
recalculate
```

For too-short plans:

```text
extend hero shots
 ↓
add strong support shot
 ↓
recalculate
```

---

## 48. Duration Adjustment Priority

Do not shorten all shots equally.

Priority:

1. preserve hero/highlight shots
2. preserve closing coherence
3. shorten low-priority supporting shots
4. remove redundant detail shots
5. adjust transition duration

---

## 49. Plan Validation

Before render, validate:

* valid plan version
* all media IDs exist
* all source ranges are valid
* shot IDs are unique
* timeline has no unintended gaps
* timeline ordering is valid
* target duration is within tolerance
* Story scenes are represented
* no hard-excluded media appears
* no exact duplicate media reuse
* resolution is valid

---

## 50. Reel Plan Immutability

Once rendering begins, the plan should be treated as immutable for that render attempt.

If editorial changes are required:

```text
create new plan
```

rather than silently mutating the active one.

This improves reproducibility.

---

## 51. Plan Versioning

Required future field:

```text
plan_version
```

Optionally:

```text
planner_version
```

This allows comparison of Planner behavior across iterations.

---

## 52. Determinism

Given:

* same Story
* same candidate pool
* same configuration
* same Planner version

the generated plan should be reproducible unless creative randomness is explicitly enabled.

---

## 53. Creative Variants

Future versions may support:

```text
variant A
variant B
variant C
```

using seeded variation.

MVP requires only one deterministic plan.

---

## 54. Rendering Independence

`reel_plan.json` must not contain raw FFmpeg commands as the core data model.

Bad:

```json
{
  "filter_complex": "..."
}
```

Preferred:

```json
{
  "motion": "zoom_in",
  "transition": "crossfade"
}
```

The Rendering Adapter translates these intents.

---

## 55. Renderer Capability Awareness

Planner may only request capabilities supported by the renderer capability contract.

Example:

```text
supported transitions
supported photo motions
supported audio operations
```

Unsupported planning instructions must fail before rendering.

---

## 56. Configuration

Planner behavior should be configuration-driven.

Example:

```yaml
reel:
  target_duration: 40
  min_duration: 38
  max_duration: 42
  width: 1080
  height: 1920
  fps: 30

planner:
  min_shots: 15
  max_shots: 25
  default_transition: cut
```

---

## 57. Default FPS

Recommended MVP baseline:

```text
30 fps
```

60 fps should not be required by default.

Reasons:

* faster render
* smaller output
* adequate for typical Reels
* mixed-source compatibility

High-frame-rate output may be optional later.

---

## 58. Source FPS

Source videos may have different FPS.

Planner should not attempt to normalize source FPS itself.

Renderer handles technical normalization.

---

## 59. HDR

HDR handling is technical rendering behavior.

Planner may preserve metadata hints but does not perform HDR conversion.

Existing audit/render capabilities should be reused.

---

## 60. Failure Isolation

Possible Planner failures:

```text
ReelPlanInsufficientMedia
ReelPlanInvalidDuration
ReelPlanInvalidMediaReference
ReelPlanUnsupportedCapability
ReelPlanStoryCoverageError
```

Planning failure must occur before expensive rendering.

---

## 61. Testing Requirements

Automated tests should cover:

* 40-second duration budgeting
* minimum/maximum duration
* shot ordering
* source in/out validation
* photo duration
* video duration
* transition overlap
* scene coverage
* duplicate rejection
* photo/video mix behavior
* small candidate pools
* large candidate pools
* serialization
* deterministic output

---

## 62. Real-World Evaluation

For real travel projects, inspect:

```text
Does pacing feel natural?
Are hero shots long enough?
Are details too long?
Are videos cut at useful moments?
Do transitions feel excessive?
Does the closing feel complete?
Does the Reel land near 40 seconds?
```

Human viewing remains mandatory during tuning.

---

## 63. Common Failure Modes

### Uniform Timing

Every shot receives the same duration.

### Hyperactive Editing

Too many sub-second cuts.

### Slideshow Editing

Every photo remains too long.

### Transition Abuse

Every shot uses a flashy transition.

### Story Drift

Planner changes scene order unnecessarily.

### Duration Drift

Rendered output misses target duration substantially.

### Video Waste

Planner uses uninteresting beginning of clips.

### Landscape Rejection

Useful wide shots are discarded because of 9:16.

---

## 64. Quality Gates

A Reel Planner implementation must not be approved if it:

1. directly invokes FFmpeg
2. rewrites Story Engine narrative without justification
3. treats selected candidate media as automatically final
4. ignores target-duration budget
5. uses raw provider-specific AI data
6. generates unsupported renderer operations
7. lacks plan validation
8. cannot explain shot ordering through structured story/priority data
9. reuses exact media unnecessarily
10. creates an opaque plan that cannot be inspected before rendering

---

## 65. Baseline Decision

The Reel Planner is the editorial execution-planning layer.

Its contract is:

> Convert the approved travel story into a deterministic, inspectable and rendering-independent 40-second edit plan.

The Story Engine answers:

> What story should we tell?

The Reel Planner answers:

> Which exact shots tell that story, and how much timeline budget does each receive?

The Rendering Engine answers:

> How do we technically produce those shots and transitions?
