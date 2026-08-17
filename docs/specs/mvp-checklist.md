# AI Travel Reel Generator — MVP Implementation Checklist

**Document Version:** 1.0
**Status:** Baseline
**Product:** AI Travel Reel Generator
**Target:** Automatic ~40-second vertical travel Reel from user photos and videos

---

## 1. MVP Definition

The MVP is complete when a user can provide a travel-media folder containing photos and videos and execute one workflow that produces a usable approximately 40-second vertical Reel.

Target experience:

```text
Travel Photos + Videos
        ↓
AI Travel Reel Generator
        ↓
Automatic Analysis
        ↓
AI Understanding
        ↓
Automatic Selection
        ↓
Story Generation
        ↓
40-second Edit Plan
        ↓
Automatic Rendering
        ↓
QA
        ↓
reel.mp4
```

The MVP must minimize manual editing.

---

## 2. Primary User Workflow

Target command:

```powershell
travel-reel build examples\Korea2026
```

Equivalent Python module execution is acceptable before packaging:

```powershell
python -m travel_reel.cli build examples\Korea2026
```

The user should not need to manually run every internal stage for normal use.

---

## 3. MVP Output

A successful build should eventually produce:

```text
output/
├── analysis.json
├── trip_manifest.json
├── reel_plan.json
├── reel.mp4
└── qa_report.json
```

Additional logs and temporary files are allowed.

---

## 4. Existing Foundation

Already implemented before the remaining MVP work:

### Sprint 1 — Trip Analyzer

Status:

```text
COMPLETED
```

Capabilities:

* recursive travel-media scanning
* photo/video detection
* basic metadata extraction
* capture-date extraction
* GPS extraction when available
* analysis summary
* `analysis.json`

---

## 5. Sprint 2 — Trip Manifest

Status:

```text
COMPLETED
```

Capabilities:

* canonical Trip Manifest
* stable media IDs
* photo/video separation
* reserved AI fields
* `trip_manifest.json`
* same-pass generation from analyzer result

Trip Manifest is the SSOT for downstream stages.

---

## 6. Current Baseline

The following specifications define the implementation contract:

```text
docs/specs/system-architecture.md
docs/specs/trip-manifest.md
docs/specs/media-analyzer.md
docs/specs/vision-provider.md
docs/specs/scoring-system.md
docs/specs/media-selector.md
docs/specs/story-engine.md
docs/specs/reel-planner.md
docs/specs/renderer.md
docs/specs/mvp-checklist.md
```

Implementation must follow these documents unless an explicit architecture decision changes the baseline.

---

# Sprint 3 — Vision Intelligence

## 7. Goal

Automatically understand the visual content of travel photos and videos.

Required result:

```text
trip_manifest.json
```

is enriched with semantic media information.

---

## 8. Sprint 3 Required Features

* [ ] define Vision Provider interface
* [ ] support provider configuration
* [ ] analyze photos
* [ ] analyze representative video frames
* [ ] generate concise descriptions
* [ ] generate normalized tags
* [ ] identify broad travel categories
* [ ] identify visible scene type
* [ ] identify useful motion/action hints
* [ ] preserve provider confidence where available
* [ ] persist Vision results to Trip Manifest
* [ ] cache Vision results
* [ ] skip unchanged media on rerun
* [ ] handle provider failure gracefully
* [ ] avoid unsupported factual claims

---

## 9. Sprint 3 Video Strategy

MVP must not upload every frame of every video.

Recommended:

```text
video
 ↓
representative frame extraction
 ↓
Vision analysis
 ↓
aggregated video description
```

Sampling must remain bounded and cost-aware.

---

## 10. Sprint 3 Acceptance Criteria

Sprint 3 passes when:

* [ ] photos receive semantic descriptions
* [ ] videos receive semantic descriptions
* [ ] tags are machine-readable
* [ ] travel categories are available
* [ ] results survive process restart
* [ ] rerunning does not unnecessarily repeat Vision requests
* [ ] Vision provider can be changed without rewriting downstream modules
* [ ] original media remains untouched

---

# Sprint 4 — Scoring and Selection

## 11. Goal

Automatically determine which travel media is most useful for a Reel.

Pipeline:

```text
Vision-enriched Manifest
        ↓
Scoring
        ↓
Selection
        ↓
Story-ready Candidate Pool
```

---

## 12. Sprint 4 Scoring Features

* [ ] technical score
* [ ] composition score
* [ ] travel-relevance score
* [ ] story-value score
* [ ] uniqueness score
* [ ] emotion/human-interest score
* [ ] vertical-suitability score
* [ ] penalties
* [ ] normalized final score
* [ ] score breakdown
* [ ] concise score reasons
* [ ] scoring version

---

## 13. Sprint 4 Duplicate Handling

* [ ] detect exact duplicates
* [ ] detect useful near-duplicate groups
* [ ] suppress burst-photo saturation
* [ ] preserve best representative
* [ ] expose duplicate reasoning

Duplicate detection must not depend entirely on an LLM.

---

## 14. Sprint 4 Selection Features

* [ ] hard rejection
* [ ] soft ranking
* [ ] candidate-pool generation
* [ ] scene diversity
* [ ] temporal diversity
* [ ] category diversity
* [ ] location diversity when information exists
* [ ] photo/video balance
* [ ] selfie saturation control
* [ ] scene saturation control
* [ ] selection rank
* [ ] selection reasons
* [ ] selector version

---

## 15. Sprint 4 Acceptance Criteria

Sprint 4 passes when:

* [ ] candidate selection is not simple global top-N
* [ ] obvious poor media ranks below strong media
* [ ] duplicate bursts do not dominate
* [ ] one attraction does not dominate without justification
* [ ] usable videos remain represented
* [ ] multi-day coverage is reasonable
* [ ] selected candidate IDs are valid
* [ ] selection is reproducible
* [ ] scoring and selection can run without new Vision calls

---

# Sprint 5 — Story Engine

## 16. Goal

Convert selected memories into a structured short-form travel story.

---

## 17. Sprint 5 Required Features

* [ ] Story Provider abstraction
* [ ] structured Story schema
* [ ] candidate-media input
* [ ] narrative scene grouping
* [ ] hook selection
* [ ] arrival/establishing logic when supported
* [ ] exploration grouping
* [ ] experience grouping
* [ ] highlight identification
* [ ] closing strategy
* [ ] scene priority
* [ ] pacing intent
* [ ] optional concise text overlays
* [ ] story version
* [ ] story validation

---

## 18. Sprint 5 Grounding Requirements

The Story Engine must not invent:

* locations
* activities
* dates
* landmarks
* events

Unsupported information should remain generic.

---

## 19. Sprint 5 Acceptance Criteria

Sprint 5 passes when:

* [ ] output is structured and machine-readable
* [ ] all referenced media IDs exist
* [ ] story has intentional opening
* [ ] story has progression
* [ ] major trip moments are represented
* [ ] story has intentional closing
* [ ] no unsupported travel facts are invented
* [ ] Story Engine operates on candidate pool rather than full raw library
* [ ] story can be regenerated without rerunning Vision

---

# Sprint 6 — Reel Planner

## 20. Goal

Convert Story Engine output into an executable approximately 40-second edit plan.

---

## 21. Sprint 6 Required Features

* [ ] define Reel Plan schema
* [ ] generate stable shot IDs
* [ ] choose final shots from candidate pool
* [ ] assign shot order
* [ ] assign photo durations
* [ ] assign video source-in/source-out
* [ ] assign scene IDs
* [ ] assign story roles
* [ ] assign photo motion intent
* [ ] assign crop intent
* [ ] assign transition intent
* [ ] assign overlay timing
* [ ] describe BGM intent
* [ ] calculate timeline
* [ ] validate timeline
* [ ] serialize `reel_plan.json`

---

## 22. Sprint 6 Duration Target

Default:

```text
target = 40 seconds
```

Initial acceptable range:

```text
38–42 seconds
```

Configuration must allow future adjustment.

---

## 23. Sprint 6 Shot Target

Recommended:

```text
15–25 final shots
```

The Planner must not force this range when source media is insufficient.

---

## 24. Sprint 6 Acceptance Criteria

Sprint 6 passes when:

* [ ] Reel Plan is inspectable before rendering
* [ ] total duration is within configured tolerance
* [ ] all media references are valid
* [ ] video source ranges are valid
* [ ] important Story scenes receive shots
* [ ] exact duplicate media is not reused
* [ ] transitions are renderer-supported
* [ ] plan contains no raw FFmpeg commands
* [ ] plan generation is reproducible

---

# Sprint 7 — Rendering Integration

## 25. Goal

Turn `reel_plan.json` into a real MP4 using the existing `video-autopilot-kit` rendering stack.

---

## 26. Mandatory Engineering Rule

Before writing a new rendering implementation:

```text
SEARCH EXISTING REPOSITORY
        ↓
REUSE
        ↓
WRAP
        ↓
EXTEND
        ↓
ONLY THEN CREATE NEW CODE
```

Travel Reel must not duplicate existing FFmpeg functionality without justification.

---

## 27. Existing Capabilities to Investigate and Reuse

At minimum inspect existing implementations related to:

```text
shorts_vertical
effects
shorts_captions
delivery_qa
post_export
silent_vlog_maker
FFmpeg utilities
FFprobe utilities
```

Actual repository APIs must be confirmed before implementation.

---

## 28. Sprint 7 Required Features

* [ ] Travel Reel rendering adapter
* [ ] media-ID path resolution
* [ ] source validation
* [ ] photo-to-video rendering
* [ ] Ken Burns / subtle photo motion
* [ ] portrait normalization
* [ ] landscape normalization
* [ ] blur-fill where required
* [ ] video trimming
* [ ] phone rotation handling
* [ ] FPS normalization
* [ ] basic transitions
* [ ] text overlays
* [ ] BGM
* [ ] audio normalization where applicable
* [ ] H.264 MP4 output
* [ ] render error reporting

---

## 29. V1 Render Target

```text
Resolution: 1080 × 1920
Aspect ratio: 9:16
FPS: 30
Container: MP4
Video codec: H.264
Pixel format: yuv420p
```

---

## 30. Sprint 7 Acceptance Criteria

Sprint 7 passes when:

* [ ] `reel_plan.json` can produce `reel.mp4`
* [ ] source media is never modified
* [ ] output is portrait 9:16
* [ ] landscape media does not create unintended black bars
* [ ] phone video orientation is correct
* [ ] photo motion works
* [ ] video trimming works
* [ ] transitions work
* [ ] text overlays work
* [ ] BGM works
* [ ] renderer does not require CapCut GUI
* [ ] existing renderer code is reused wherever practical

---

# Sprint 8 — QA and One-Command Build

## 31. Goal

Turn individual pipeline components into the actual user-facing MVP.

Target:

```powershell
python -m travel_reel.cli build examples\Korea2026
```

---

## 32. Pipeline Orchestration

The build command should orchestrate:

```text
Analyze
  ↓
Manifest
  ↓
Vision
  ↓
Score
  ↓
Select
  ↓
Story
  ↓
Plan
  ↓
Render
  ↓
QA
```

Each stage should remain independently testable.

---

## 33. Resume Capability

A failed build should not always restart from zero.

Where practical:

```text
Vision cached
Story persisted
Plan persisted
```

should allow continuation.

Example:

```text
Render failed
↓
fix renderer
↓
rerun render
```

without repeating paid Vision processing.

---

## 34. Required QA

At minimum:

* [ ] output file exists
* [ ] FFprobe can read output
* [ ] duration within configured tolerance
* [ ] width = 1080
* [ ] height = 1920
* [ ] expected FPS
* [ ] valid video stream
* [ ] valid audio stream when BGM configured
* [ ] no obvious unintended black borders
* [ ] QA report written

---

## 35. QA Output

Required:

```text
qa_report.json
```

The report should include:

```text
pass/fail
duration
resolution
fps
audio presence
warnings
errors
```

---

## 36. One-Command Acceptance Criteria

Sprint 8 passes when the user can:

1. place travel photos/videos in a project folder
2. execute one build command
3. wait for processing
4. receive `reel.mp4`
5. inspect `qa_report.json`

without manually editing the timeline.

---

# MVP End-to-End Acceptance

## 37. Golden Test Project

The initial real-world validation project should use:

```text
examples/Korea2026
```

with a curated representative subset of actual travel media.

The test set should contain enough variety to expose real-world issues without requiring the entire original trip archive during every development cycle.

---

## 38. Golden Test Media Mix

Recommended fixture should include:

```text
portrait photos
landscape photos
portrait videos
landscape videos
people
landmarks
food
street scenes
transportation
day scenes
night scenes
```

Where available, include mixed video FPS and phone rotation metadata.

---

## 39. Golden Test Objective

The final system should produce:

```text
Korea2026
    ↓
approximately 40-second Reel
    ↓
1080 × 1920 MP4
```

with no manual timeline editing.

---

## 40. Editorial Acceptance

The generated Reel should satisfy:

* [ ] opening captures attention
* [ ] travel context is understandable
* [ ] multiple trip moments are represented
* [ ] duplicate imagery is controlled
* [ ] photos and videos are reasonably balanced
* [ ] visual sequence is not obviously random
* [ ] major moments receive appropriate emphasis
* [ ] closing feels intentional
* [ ] total pacing feels appropriate for a Reel

This requires human review.

---

## 41. Technical Acceptance

The generated Reel must satisfy:

* [ ] MP4 opens successfully
* [ ] 1080 × 1920
* [ ] approximately 40 seconds
* [ ] correct orientation
* [ ] no unintended black borders
* [ ] no broken media
* [ ] no severe visual corruption
* [ ] BGM audible when configured
* [ ] no severe audio clipping
* [ ] output QA passes

---

## 42. AI Acceptance

The AI pipeline should satisfy:

* [ ] media descriptions are generally accurate
* [ ] obvious poor media is deprioritized
* [ ] candidate pool represents the trip
* [ ] story does not fabricate major facts
* [ ] story structure is coherent
* [ ] Planner output matches Story intent
* [ ] reruns are reasonably reproducible

---

# MVP Non-Goals

## 43. Explicitly Out of Scope

The following are not required to declare MVP complete:

```text
Remotion
React rendering
Web application
mobile application
automatic Instagram upload
automatic TikTok upload
automatic YouTube upload
generative image creation
image-to-video generation
AI avatar
automatic voice narration
Whisper transcription
complex motion graphics
full CapCut GUI automation
multi-user cloud platform
4K rendering
real-time rendering
```

These may be considered later.

---

## 44. Why These Are Deferred

The primary product hypothesis is:

> Can AI reliably turn a user's real travel photos and videos into a watchable short travel Reel with minimal manual editing?

Features that do not directly validate this hypothesis should not delay MVP completion.

---

# Development Rules

## 45. Preserve Existing Working Code

Existing `video-autopilot-kit` functionality must not be casually rewritten.

Changes should prefer:

```text
new travel_reel module
adapter
small compatible extension
```

over invasive modification.

---

## 46. Source Media Safety

Original travel media must always remain untouched.

No pipeline stage may destructively:

```text
rename
move
overwrite
delete
```

source photos or videos.

---

## 47. Manifest Stability

Stable media IDs must survive downstream processing.

Do not regenerate IDs because Vision, scoring, Story, or rendering logic changes.

---

## 48. SSOT

`trip_manifest.json` remains the canonical project state.

Derived artifacts may exist, but media identity and accumulated enrichment belong to the Manifest.

---

## 49. Provider Boundaries

Cloud providers must remain behind interfaces.

At minimum:

```text
Vision Provider
Story Provider
```

Business logic must not depend directly on a single vendor SDK.

---

## 50. Cost Control

Paid AI operations must support:

```text
caching
skip unchanged
retry limits
bounded video-frame sampling
```

A rendering failure must not automatically trigger paid Vision reprocessing.

---

## 51. Explainability

Important automated decisions should expose concise structured reasons.

Examples:

```text
score_reason
selection_reason
story role
shot role
```

Do not store hidden chain-of-thought.

---

## 52. Determinism

Deterministic stages should remain deterministic.

Creative AI stages should use:

```text
structured output
versioned prompts
persisted results
```

to improve reproducibility.

---

## 53. Validation Before Expensive Work

Every stage should validate its input before starting expensive processing.

Example:

```text
invalid Reel Plan
```

must be detected before full FFmpeg rendering.

---

## 54. Tests

Every Sprint should add tests for new behavior.

Minimum categories:

```text
unit tests
schema tests
failure-path tests
smoke tests
```

Cloud services should be mocked in normal automated tests.

---

## 55. Git Checkpoints

Each completed Sprint should receive:

```text
commit
tag
```

Recommended future tags:

```text
sprint-3
sprint-4
sprint-5
sprint-6
sprint-7
sprint-8
```

A Sprint must pass its acceptance criteria before tagging.

---

# Implementation Order

## 56. Required Order

Continue development in this order:

```text
Sprint 3
Vision Intelligence
        ↓
Sprint 4
Scoring + Media Selection
        ↓
Sprint 5
Story Engine
        ↓
Sprint 6
Reel Planner
        ↓
Sprint 7
Rendering Integration
        ↓
Sprint 8
QA + One-Command Build
```

Do not jump directly to final rendering before upstream contracts are validated.

---

## 57. Why This Order

The dependency chain is:

```text
Renderer quality
depends on
Reel Plan quality

Reel Plan quality
depends on
Story quality

Story quality
depends on
Selection quality

Selection quality
depends on
Vision quality
```

Rendering first would optimize the least uncertain part of the product.

The primary risk is editorial intelligence.

---

# MVP Definition of Done

## 58. Product Definition of Done

AI Travel Reel Generator MVP is DONE when:

```text
User provides travel photos/videos
            ↓
runs one command
            ↓
system analyzes media
            ↓
AI understands media
            ↓
AI selects representative memories
            ↓
AI constructs a travel story
            ↓
Planner creates ~40-second timeline
            ↓
existing FFmpeg engine renders it
            ↓
QA validates it
            ↓
user receives reel.mp4
```

with no required manual timeline editing.

---

## 59. Success Criterion

The MVP does not need to replace a professional human video editor.

It succeeds when:

> The automatically generated Reel is good enough that the user would realistically consider posting it, or would need only minor optional refinement.

---

## 60. Final Baseline Decision

Development must optimize for:

```text
Reliable automation
+
good travel-memory selection
+
coherent storytelling
+
reusable existing rendering
+
inspectable intermediate artifacts
```

rather than maximum feature count.

The MVP question is simple:

> Can the user drop in a travel collection and receive a credible Reel automatically?

Until the answer is consistently yes, additional platform, UI, generative-video, and advanced motion-graphics features remain secondary.
