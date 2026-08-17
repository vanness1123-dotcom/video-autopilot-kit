# AI Travel Reel Generator — Renderer Specification

**Document Version:** 1.0
**Status:** Baseline
**Component:** Rendering Adapter / Rendering Engine
**Related Documents:** `system-architecture.md`, `trip-manifest.md`, `story-engine.md`, `reel-planner.md`

---

## 1. Purpose

The Renderer converts an approved `reel_plan.json` into the final vertical travel Reel.

Its responsibility is to answer:

> How do we technically execute the approved edit plan and produce a reliable MP4?

The Renderer is not an editorial intelligence component.

It executes decisions made upstream.

---

## 2. Core Architecture Decision

AI Travel Reel Generator must reuse the existing rendering capabilities already present in `video-autopilot-kit`.

The project must not create a second independent video-rendering stack unless an existing capability is demonstrably insufficient.

Preferred architecture:

```text
reel_plan.json
      ↓
Travel Reel Rendering Adapter
      ↓
Existing video-autopilot-kit modules
      ↓
FFmpeg / FFprobe
      ↓
QA
      ↓
final Reel
```

---

## 3. Existing Capabilities to Reuse

Existing repository capabilities identified as reusable include:

```text
shorts_vertical
effects
shorts_captions
delivery_qa
post_export
silent_vlog_maker
FFmpeg / FFprobe utilities
```

Where applicable, existing implementations should be wrapped through adapters rather than copied.

---

## 4. Responsibilities

The rendering layer is responsible for:

* resolving media IDs to source files
* validating source availability
* creating 9:16 shots
* trimming video segments
* rendering photo shots
* applying photo motion
* applying crop/fill behavior
* normalizing source media
* applying transitions
* rendering text overlays
* mixing background music
* normalizing audio where required
* encoding MP4
* running delivery QA
* reporting rendering failures

---

## 5. Non-Responsibilities

The Renderer must not:

* perform AI Vision analysis
* score media
* select media
* rewrite the story
* independently replace planned shots
* generate a new Reel Plan
* silently change narrative ordering
* modify original source files

---

## 6. Rendering Adapter

A new Travel Reel-specific adapter should exist between `reel_plan.json` and legacy rendering modules.

Conceptually:

```text
src/travel_reel/renderer.py
```

acts as:

```text
Reel Plan
   ↓
validation
   ↓
capability translation
   ↓
existing renderer functions
```

This prevents Travel Reel domain logic from becoming tightly coupled to FFmpeg syntax.

---

## 7. Why an Adapter Is Required

The existing rendering system predates AI Travel Reel Generator.

Its APIs may not directly understand concepts such as:

```text
media_id
scene_id
story role
shot priority
crop intent
motion intent
```

The Adapter translates these editorial concepts into existing renderer inputs.

It must not duplicate existing rendering algorithms unnecessarily.

---

## 8. Input Contract

Primary input:

```text
reel_plan.json
```

Additional required context may include:

```text
trip_manifest.json
trip source folder
render configuration
BGM path
output path
```

The Renderer should not require Vision-provider responses.

---

## 9. Output Contract

Primary output:

```text
reel.mp4
```

Recommended future project layout:

```text
output/
└── <trip-name>/
    ├── analysis.json
    ├── trip_manifest.json
    ├── reel_plan.json
    ├── reel.mp4
    └── qa_report.json
```

Migration to this directory structure is not mandatory for the current implementation.

---

## 10. V1 Delivery Format

Baseline:

```text
Container: MP4
Video codec: H.264
Resolution: 1080 × 1920
Aspect ratio: 9:16
FPS: 30
Pixel format: yuv420p
```

Audio should use a broadly compatible codec such as AAC when audio exists.

---

## 11. Compatibility Goal

The output should be compatible with common:

```text
Instagram Reels
Facebook Reels
YouTube Shorts
mobile players
desktop players
```

Platform-specific upload automation is outside Renderer scope.

---

## 12. Source Resolution

The Renderer receives `media_id`.

It must resolve:

```text
media_id
   ↓
Trip Manifest
   ↓
relative source path
   ↓
trip source root
   ↓
actual file
```

The Reel Plan should not duplicate machine-specific absolute source paths unnecessarily.

---

## 13. Missing Source Media

If planned source media no longer exists, rendering must fail explicitly.

Example:

```text
RenderSourceMissing
```

The Renderer must not silently substitute another media item.

Candidate fallback selection belongs upstream.

---

## 14. Original Media Protection

Original travel media is read-only input.

Renderer must never overwrite:

```text
Photos/
Videos/
```

Temporary and derived assets must be written outside the source-media directories.

---

## 15. Temporary Workspace

Rendering may require temporary:

```text
normalized clips
extracted frames
subtitle files
audio intermediates
transition segments
```

These should be stored in a dedicated temporary workspace.

Example:

```text
output/<trip-name>/work/
```

or an OS-managed temporary directory.

---

## 16. Vertical Normalization

All shots must ultimately conform to:

```text
1080 × 1920
```

without accidental black bars.

Existing vertical-normalization functionality should be reused.

---

## 17. Portrait Media

Native portrait media should generally use:

```text
scale
crop
```

with subject-safe framing.

Unnecessary blur-fill should be avoided when the source already fills the vertical canvas appropriately.

---

## 18. Landscape Media

Landscape media may use:

```text
subject-aware crop
blur-fill background
Ken Burns movement
fit where editorially justified
```

Landscape media must not automatically be rejected.

Existing blur-fill capability should be reused.

---

## 19. Blur-Fill

Existing blur-fill behavior is valuable for travel photos and landscape video.

Conceptually:

```text
source
 ├─ foreground fitted media
 └─ enlarged blurred background
```

The output must not expose unintended black borders.

---

## 20. Photo Rendering

A photo shot must be converted into a timed video segment.

Required inputs include:

```text
source image
duration
motion intent
crop intent
output dimensions
fps
```

The existing photo/video composition utilities should be reused where possible.

---

## 21. Ken Burns

Existing Ken Burns functionality should be reused.

Supported editorial intents may include:

```text
zoom_in
zoom_out
pan_left
pan_right
ken_burns
```

The Adapter maps these intents to renderer-specific parameters.

---

## 22. Motion Restraint

Photo movement should remain subtle.

Avoid:

```text
extreme zoom
rapid pan
constant aggressive movement
```

The objective is to make still media feel alive without looking artificially animated.

---

## 23. Video Rendering

Video shots require:

```text
source_in
source_out
duration
vertical normalization
fps normalization
codec normalization
```

The Renderer must validate source ranges before starting expensive rendering.

---

## 24. Video Trim

The Renderer executes the Planner's requested source range.

It must not independently choose a different segment unless explicitly implementing a documented technical correction.

---

## 25. Rotation

Phone video rotation metadata must be handled correctly.

The output must visually match intended orientation regardless of how rotation is stored in source metadata.

---

## 26. Mixed FPS

Source clips may include:

```text
24 fps
25 fps
30 fps
60 fps
variable frame rate
```

Renderer must normalize these to the configured output FPS.

Baseline:

```text
30 fps
```

---

## 27. HDR / SDR

Travel phone footage may contain HDR.

Existing HDR detection or normalization functionality should be reused where available.

The baseline delivery target should prioritize predictable social-media playback.

HDR-to-SDR conversion may therefore be required for mixed-source projects.

---

## 28. Color Handling

The Renderer may apply technically necessary color conversion.

Creative grading should remain restrained unless explicitly configured.

Do not apply heavy filters globally by default.

---

## 29. Transitions

The Renderer executes transition intent from Reel Planner.

Baseline supported transitions should remain limited.

Recommended:

```text
cut
crossfade
fade
dip_to_black
```

Existing `xfade` functionality should be reused where appropriate.

---

## 30. Default Transition

Default:

```text
cut
```

This reduces unnecessary rendering complexity and prevents transition-heavy output.

---

## 31. Transition Validation

Before rendering, verify:

* transition type supported
* transition duration valid
* adjacent shots long enough
* total timeline remains valid

Unsupported transition requests must fail early.

---

## 32. Text Overlays

Renderer should support concise text overlays from Reel Plan.

Examples:

```text
SEOUL
DAY 1
HONGDAE
LOTTE WORLD
```

Existing subtitle/text rendering functionality should be reused where suitable.

---

## 33. Text Rendering Strategy

Where existing ASS-based text rendering is suitable, it should be preferred.

Advantages:

```text
positioning
font sizing
outline
timing
Unicode support
```

The Renderer Adapter may convert Reel Plan overlay objects into existing ASS/subtitle structures.

---

## 34. Text Safe Area

Text must avoid typical social-media UI obstruction zones.

Exact safe-area values should be configuration-driven.

---

## 35. Subtitle Architecture

Text overlays and narration subtitles remain separate concepts.

Existing subtitle capabilities may later support narration.

V1 does not require automatic narration subtitles.

---

## 36. BGM

The Renderer should support background music.

Input may be:

```text
user-provided BGM
configured local BGM
```

Automatic music generation is outside V1 scope.

---

## 37. Existing BGM Capabilities

Where available, reuse existing functionality for:

```text
BGM segment selection
looping
fade
mixing
loudness handling
```

Do not create a second independent audio-mixing system without justification.

---

## 38. Source Audio

Travel videos may contain useful ambient audio.

V1 may initially choose one of two policies:

```text
BGM dominant
```

or:

```text
BGM + selected source audio
```

The exact default should be validated during MVP testing.

---

## 39. Audio Ducking

Existing audio-chain functionality may be reused where relevant.

If source audio is retained, BGM may be reduced during important source-audio moments.

Advanced automated audio storytelling is post-MVP.

---

## 40. Loudness

Final audio should avoid:

```text
clipping
large volume jumps
inaudible BGM
excessively loud BGM
```

Existing loudness-normalization functionality should be reused.

---

## 41. Encoding

Preferred baseline encoder:

```text
libx264
```

Hardware encoding may be introduced later as an optimization.

Correctness and compatibility take priority over maximum rendering speed for MVP.

---

## 42. Pixel Format

Recommended:

```text
yuv420p
```

for broad playback compatibility.

---

## 43. Render Performance

Rendering a 40-second Reel should not require unreasonable resources.

Optimization opportunities include:

```text
cached normalized media
cached photo segments
parallel preprocessing
hardware encoding
```

These are secondary to deterministic correctness.

---

## 44. Progress Reporting

Renderer should eventually expose progress.

Example stages:

```text
Preparing media
Rendering shots
Applying transitions
Mixing audio
Encoding final video
Running QA
```

This is useful because FFmpeg operations may take significant time.

---

## 45. Render Logs

Useful log fields include:

```text
plan ID/version
shot count
source media count
output settings
FFmpeg failures
render duration
output path
QA result
```

Avoid logging secrets or unnecessary personal metadata.

---

## 46. Error Model

Potential errors:

```text
RenderSourceMissing
RenderUnsupportedMedia
RenderInvalidPlan
RenderFFmpegError
RenderTransitionError
RenderAudioError
RenderEncodingError
RenderQAError
```

Errors must identify the failing shot or operation where practical.

---

## 47. Failure Isolation

Intermediate rendering may allow the system to identify:

```text
shot-012 failed
```

instead of returning only:

```text
FFmpeg failed
```

This dramatically improves debugging.

---

## 48. Rendering Determinism

Given:

```text
same Reel Plan
same source media
same renderer version
same FFmpeg version
same configuration
```

the resulting editorial timeline should be reproducible.

Bit-identical encoding is not required.

---

## 49. Rendering Adapter Contract

Conceptually:

```text
render_reel(
    manifest,
    reel_plan,
    config,
    output_path
)
```

The exact Python API may differ.

The architectural boundary must remain.

---

## 50. Existing Module Reuse

Before implementing any new renderer feature, development must search the repository for equivalent existing functionality.

Priority:

```text
reuse
↓
wrap
↓
extend
↓
only then create new implementation
```

This is a mandatory engineering rule for the Travel Reel module.

---

## 51. No Remotion Requirement

Remotion is not required for V1.

The repository already has a substantial FFmpeg-based rendering stack.

Introducing:

```text
Node.js
React
Remotion
```

would create a second rendering ecosystem and increase maintenance cost.

Reconsider only if future requirements demand advanced template-driven motion graphics that are difficult to maintain in FFmpeg.

---

## 52. CapCut Role

CapCut must not be the core automated renderer.

CapCut may remain:

```text
optional manual refinement
optional draft export
```

The automated MVP must be capable of producing a final Reel without GUI automation.

---

## 53. Why CapCut Is Optional

GUI automation is vulnerable to:

```text
UI changes
window state
timing
version changes
local machine state
```

A deterministic FFmpeg path is more appropriate for core automation.

---

## 54. Renderer Capability Contract

Renderer should expose supported capabilities.

Conceptually:

```json
{
  "photo_motion": [
    "static",
    "zoom_in",
    "zoom_out",
    "ken_burns"
  ],
  "transitions": [
    "cut",
    "crossfade",
    "fade"
  ],
  "text_overlay": true,
  "bgm": true,
  "blur_fill": true
}
```

Reel Planner must plan only supported operations.

---

## 55. Preflight Validation

Before starting render:

```text
validate plan
validate source files
validate FFmpeg
validate output directory
validate BGM
validate capabilities
```

Fail before rendering when a required dependency is unavailable.

---

## 56. FFmpeg Detection

The existing Windows FFmpeg environment must remain supported.

Known local installation may include:

```text
C:\Tools\ffmpeg\bin\ffmpeg.exe
```

However, code should prefer configurable discovery rather than hard-coding a single machine path.

---

## 57. FFprobe

FFprobe should be used for:

```text
duration validation
stream metadata
codec inspection
resolution inspection
post-render verification
```

Existing utilities should be reused.

---

## 58. Output QA

Rendering is not complete when FFmpeg returns exit code zero.

The final file must pass delivery QA.

---

## 59. Existing QA Reuse

Existing QA functionality should be reused for checks such as:

```text
black borders
unexpected silence
flicker
duration
resolution
playback compatibility
```

Exact available checks should be confirmed during implementation.

---

## 60. Required V1 QA

At minimum verify:

```text
file exists
file is readable
video stream exists
resolution = 1080 × 1920
duration within tolerance
expected FPS
audio stream valid when required
no obvious unintended black borders
```

---

## 61. QA Report

Recommended future output:

```text
qa_report.json
```

Conceptual structure:

```json
{
  "passed": true,
  "duration_seconds": 40.1,
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "audio_present": true,
  "warnings": []
}
```

---

## 62. Render Status

Trip Manifest may eventually track:

```text
pending
rendering
completed
failed
```

with output path and limited render metadata.

The manifest should not store raw FFmpeg console output.

---

## 63. Intermediate Cleanup

Successful rendering may remove temporary assets.

Failed rendering may optionally preserve them for debugging.

This behavior should be configurable.

---

## 64. Source Changes

If source media changes after Reel Plan generation, preflight should detect incompatible changes where possible.

The Renderer must not blindly render against stale source assumptions.

---

## 65. Testing Requirements

Automated tests should cover:

```text
plan translation
missing source
photo rendering
video trim
vertical normalization
motion mapping
transition mapping
text overlay mapping
duration validation
unsupported capability
output-path handling
```

Large end-to-end video tests should remain separate from lightweight unit tests.

---

## 66. Smoke Test

A minimal renderer smoke test should use:

```text
1 photo
1 short video
1 text overlay
1 BGM
```

and produce a valid vertical MP4.

This should become a standard development validation.

---

## 67. Real-World Validation

The renderer must eventually be tested with:

```text
portrait photos
landscape photos
portrait videos
landscape videos
mixed FPS
phone rotation metadata
HEIC-derived media
HDR footage where available
```

Real travel media exposes issues synthetic tests may miss.

---

## 68. Performance Metrics

Useful metrics include:

```text
total render time
preprocessing time
encoding time
QA time
temporary storage
output file size
```

These are diagnostic metrics rather than MVP acceptance criteria.

---

## 69. Security

Renderer commands must safely handle paths containing:

```text
spaces
Unicode
parentheses
special characters
```

Command construction must avoid unsafe shell interpolation.

---

## 70. Privacy

Rendering should occur locally by default.

No source media needs to be uploaded by the Renderer.

This is an important distinction from optional cloud Vision processing.

---

## 71. V1 Scope

V1 Renderer must support:

```text
photos
videos
9:16 output
1080 × 1920
30 fps
photo motion
basic transitions
text overlays
BGM
MP4/H.264
delivery QA
```

---

## 72. Post-MVP Scope

Possible future capabilities:

```text
beat-synchronous editing
automatic source-audio highlights
advanced color grading
motion graphics
multiple style templates
GPU encoding
4K vertical output
automatic platform exports
CapCut project export
```

These must not block V1.

---

## 73. Common Failure Modes

### Renderer Rewrite

Travel Reel duplicates existing FFmpeg functionality.

### FFmpeg Leakage

Raw filter strings spread into Story or Planner modules.

### GUI Dependency

Core automation requires CapCut.

### Black Bars

Landscape media is handled incorrectly.

### Rotation Failure

Phone footage appears sideways.

### Audio Failure

BGM clips or source audio becomes excessively loud.

### Duration Drift

Final output misses Planner duration substantially.

### Silent Failure

FFmpeg succeeds but output is technically invalid.

---

## 74. Quality Gates

A Renderer implementation must not be approved if it:

1. duplicates existing renderer capabilities without justification
2. requires CapCut GUI automation
3. modifies original travel media
4. allows Story Engine to emit FFmpeg commands
5. silently substitutes missing source media
6. skips preflight validation
7. considers FFmpeg exit code alone sufficient QA
8. produces unintended black borders
9. ignores phone rotation metadata
10. lacks actionable error reporting

---

## 75. Baseline Decision

The Travel Reel Renderer is an adapter-driven execution layer built on the existing `video-autopilot-kit` rendering stack.

Its contract is:

> Faithfully execute the approved Reel Plan using reusable, deterministic FFmpeg-based capabilities and produce a validated social-media-ready MP4.

The system should not build another video editor.

It should turn the existing video engine into the reliable execution backend for AI-generated editorial decisions.
