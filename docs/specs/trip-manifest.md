# AI Travel Reel Generator — Trip Manifest Specification

**Document Version:** 1.0

> Sprint 7.5 adds additive `events` state and media-level `event` membership as defined in `event-scene-intelligence.md`. Recomputing Events preserves inventory, Vision, and scores while invalidating selection, Story, Reel Plan, and render state.
**Schema Version:** 1.0
**Status:** Baseline
**Related Architecture:** `system-architecture.md`

---

## 1. Purpose

This document defines the persistent project-state model used by the AI Travel Reel Generator.

The primary artifact is:

```text
trip_manifest.json
```

The Trip Manifest acts as the persistent **Single Source of Truth (SSOT)** for an individual travel-reel project after initial media analysis.

It provides a stable contract between:

* Media Analyzer
* Vision Provider
* Scoring System
* Media Selector
* Story Director
* Reel Planner
* Rendering Adapter

The manifest must remain inspectable, serializable, versioned, and independent from any specific AI provider.

---

## 2. Design Goals

The Trip Manifest must support:

1. deterministic identification of source media
2. progressive enrichment by downstream modules
3. resumable processing
4. inspectable AI decisions
5. schema evolution
6. provider independence
7. separation between source facts and AI-derived state
8. reproducible planning
9. debugging without rerunning the complete pipeline

The manifest is not intended to contain raw binary media.

It stores metadata, references, analysis results, editorial state, and planning state.

---

## 3. Relationship to Other Artifacts

The pipeline uses three distinct structured artifacts.

```text
analysis.json
      ↓
trip_manifest.json
      ↓
reel_plan.json
```

### `analysis.json`

Contains objective facts discovered from source media.

Examples:

* file path
* media type
* file size
* capture time
* GPS metadata

It is primarily owned by the Media Analyzer.

---

### `trip_manifest.json`

Contains persistent project state.

It starts from analyzer results and is progressively enriched by:

* Vision
* Scoring
* Selection
* Scene assignment
* Story generation

This is the primary mutable project artifact.

---

### `reel_plan.json`

Contains the final editorial execution plan.

It is produced by Reel Planner and consumed by Rendering Adapter.

It should be reproducible from the relevant state stored in the Trip Manifest.

---

## 4. Current V1 Top-Level Schema

The baseline manifest structure is:

```json
{
  "manifest_version": "1.0",
  "trip": {},
  "photos": [],
  "videos": [],
  "scenes": [],
  "story": {},
  "timeline": {},
  "render": {}
}
```

The existing Sprint 2 implementation establishes this structure.

Future schema evolution must preserve backward compatibility where practical.

---

## 5. Manifest Version

Required field:

```json
"manifest_version": "1.0"
```

Purpose:

* detect incompatible schemas
* support future migrations
* prevent silent interpretation of outdated data

The manifest version represents the **schema**, not the application release.

Future examples:

```text
1.0
1.1
2.0
```

A breaking schema change requires a major version increment.

---

## 6. Trip Object

The `trip` object describes the project itself.

Baseline:

```json
{
  "trip": {
    "name": "Korea2026",
    "source_folder": "C:\\Trips\\Korea2026",
    "generated_at": "2026-08-05T06:45:38+00:00",
    "summary": {},
    "folder_structure": []
  }
}
```

### Required baseline fields

| Field              | Type            | Description                      |
| ------------------ | --------------- | -------------------------------- |
| `name`             | string          | Human-readable trip/project name |
| `source_folder`    | string          | Source media directory           |
| `generated_at`     | ISO-8601 string | Manifest creation time           |
| `summary`          | object          | Analyzer summary                 |
| `folder_structure` | array           | Source-folder summary            |

---

## 7. Future Trip Metadata

The schema should be capable of adding:

```json
{
  "country": null,
  "cities": [],
  "timezone": null,
  "start_date": null,
  "end_date": null
}
```

These values must not be fabricated when source evidence is unavailable.

For example, a folder named:

```text
Korea2026
```

does not by itself prove:

```text
country = South Korea
city = Seoul
```

Travel context may later be supplied by the user, metadata, or AI enrichment.

---

## 8. Photos Collection

Photos are stored separately from videos:

```json
"photos": []
```

Each photo requires a deterministic unique identifier.

Example:

```json
{
  "id": "photo-...",
  "path": "Photos/arrival.jpg",
  "size_bytes": 4200000,
  "captured_at": null,
  "gps": null,
  "score": null,
  "selected": false,
  "scene_id": null,
  "tags": [],
  "description": null,
  "objects": [],
  "emotion": null
}
```

Photos and videos must not be collapsed into one generic `media` collection in V1.

---

## 9. Videos Collection

Videos are stored under:

```json
"videos": []
```

They follow the same identity and editorial principles as photos while allowing video-specific metadata.

Future video metadata should support:

```json
{
  "duration_seconds": null,
  "width": null,
  "height": null,
  "orientation": null,
  "fps": null,
  "codec": null
}
```

Exact field implementation belongs to Media Analyzer evolution.

---

## 10. Media Identity

Every media object must have a stable ID.

Examples:

```text
photo-...
video-...
```

IDs must be deterministic.

The same unchanged source file should receive the same media ID across repeated analysis runs.

IDs must not depend on:

* Vision results
* score
* selection state
* story state
* list position

This allows downstream objects to safely reference media.

---

## 11. Source Facts vs Derived State

Media fields fall into two categories.

### Source facts

Derived deterministically from source media.

Examples:

```text
path
size_bytes
captured_at
gps
width
height
duration
fps
codec
```

These are owned by Media Analyzer.

---

### Derived state

Produced by AI or editorial modules.

Examples:

```text
score
selected
scene_id
tags
description
objects
emotion
```

These must not overwrite source facts.

This separation is mandatory.

---

## 12. Vision State

Vision analysis may enrich a media item with information such as:

```json
{
  "description": "Night view over the Han River",
  "tags": [
    "night",
    "river",
    "cityscape"
  ],
  "objects": [
    "river",
    "bridge",
    "buildings"
  ],
  "emotion": "calm"
}
```

These values are examples only.

The final normalized Vision schema is defined by:

```text
vision-provider.md
```

Provider-specific response payloads must not be stored directly as the canonical schema.

---

## 13. Scoring State

A media item may eventually contain structured scoring.

The current Sprint 2 field:

```json
"score": null
```

is retained for compatibility.

Future evolution should permit a structure similar to:

```json
{
  "score": {
    "total": 0.0,
    "technical": 0.0,
    "composition": 0.0,
    "story": 0.0,
    "uniqueness": 0.0,
    "travel_relevance": 0.0,
    "duplicate_penalty": 0.0
  }
}
```

Exact scoring rules are defined in:

```text
scoring-system.md
```

No scoring formula is fixed by this document.

---

## 14. Selection State

The baseline selection field is:

```json
"selected": false
```

The Media Selector owns this state.

Future schema versions may add:

```json
{
  "selection_reason": null,
  "selection_rank": null
}
```

Selection must remain explainable.

A selected media item should eventually be traceable to an editorial reason rather than only a Boolean value.

---

## 15. Scene Assignment

Media may reference:

```json
"scene_id": null
```

A non-null `scene_id` must reference a valid entry in:

```json
"scenes": []
```

Dangling scene references are invalid.

---

## 16. Scenes Collection

Scenes represent semantic or narrative groupings of travel media.

Baseline:

```json
"scenes": []
```

Future scene objects should support concepts such as:

```json
{
  "id": "scene-001",
  "title": "Arrival",
  "media_ids": [],
  "start_time": null,
  "end_time": null,
  "location": null,
  "summary": null
}
```

Scene construction must not duplicate media objects.

Scenes reference media IDs.

---

## 17. Story State

Baseline:

```json
"story": {}
```

The Story Director owns this section.

Future state may include:

```json
{
  "title": null,
  "style": null,
  "hook": null,
  "scene_order": [],
  "ending": null
}
```

The story describes narrative intent.

It must not contain FFmpeg implementation details.

---

## 18. Timeline State

Baseline:

```json
"timeline": {}
```

This section represents high-level editorial timing state before or alongside generation of the final Reel Plan.

Possible fields include:

```json
{
  "target_duration_seconds": 40,
  "estimated_duration_seconds": null,
  "ordered_scene_ids": []
}
```

The exact Reel execution contract belongs in:

```text
reel-planner.md
```

---

## 19. Render State

Baseline:

```json
"render": {}
```

This section stores rendering intent or render status, not renderer implementation internals.

Potential future fields:

```json
{
  "aspect_ratio": "9:16",
  "resolution": "1080x1920",
  "fps": 30,
  "status": null,
  "output_path": null
}
```

The manifest must not contain raw FFmpeg command strings as its canonical rendering representation.

---

## 20. Module Ownership Matrix

| Manifest Area          | Primary Writer               |
| ---------------------- | ---------------------------- |
| `manifest_version`     | Manifest layer               |
| `trip` source metadata | Media Analyzer               |
| `photos` source facts  | Media Analyzer               |
| `videos` source facts  | Media Analyzer               |
| media semantic fields  | Vision Provider              |
| media scores           | Scoring System               |
| `selected`             | Media Selector               |
| `scene_id` / `scenes`  | Scene/Story processing       |
| `story`                | Story Director               |
| `timeline`             | Reel Planner                 |
| `render`               | Planner / Rendering pipeline |

Modules may read other sections as required.

They must only mutate fields they own unless explicitly defined by another specification.

---

## 21. Mutation Rules

The Trip Manifest is progressively enriched.

Expected lifecycle:

```text
Analyzer
   ↓
Manifest v1 base
   ↓
Vision enrichment
   ↓
Scoring enrichment
   ↓
Selection enrichment
   ↓
Scene/story enrichment
   ↓
Planning enrichment
```

A later stage must not silently delete valid results from an earlier stage.

---

## 22. Persistence Rules

Manifest writes should eventually follow safe-write behavior:

```text
serialize
    ↓
write temporary file
    ↓
validate
    ↓
atomic replace
```

This reduces the risk of a corrupted project state if execution stops during a write.

This is a future implementation requirement, not necessarily part of the existing Sprint 2 implementation.

---

## 23. Resume Behavior

The manifest must support resuming work.

Example:

```text
Analyzer       complete
Vision         complete
Selector       complete
Story          failed
```

The next execution should be capable of restarting from Story without unnecessarily repeating Analyzer or Vision.

Future processing metadata may therefore include stage status.

Example conceptual structure:

```json
{
  "pipeline": {
    "analyze": "completed",
    "vision": "completed",
    "select": "completed",
    "story": "failed",
    "plan": "pending",
    "render": "pending"
  }
}
```

This field is not mandatory for Schema 1.0.

---

## 24. Source Change Detection

A future version should detect when source media changes after analysis.

Potential mechanisms include:

* file size
* modification timestamp
* deterministic media ID
* content hash where justified

A source change may invalidate:

```text
Vision
Score
Selection
Scene assignment
Story
Plan
```

for the affected media.

The system should avoid invalidating unrelated media unnecessarily.

---

## 25. Serialization Rules

The persistent manifest must remain JSON-compatible.

Recommended representations:

| Python Concept    | JSON Representation |
| ----------------- | ------------------- |
| `Path`            | string              |
| `datetime`        | ISO-8601 string     |
| enum              | stable string value |
| optional value    | value or `null`     |
| collection        | JSON array          |
| structured object | JSON object         |

Provider SDK objects must never be serialized directly into the canonical manifest.

---

## 26. Validation Rules

At minimum, manifest validation should eventually verify:

* supported `manifest_version`
* unique photo IDs
* unique video IDs
* no photo/video ID collision
* valid media paths
* valid scene references
* valid scene media references
* score ranges where applicable
* timeline duration constraints
* required top-level sections

Invalid state must fail explicitly rather than being silently ignored.

---

## 27. Backward Compatibility

Sprint 2 established Schema 1.0.

Future implementation must not casually break existing manifests.

Changes fall into three categories.

### Additive

Example:

```text
adding width
adding duration
adding selection_reason
```

Normally compatible.

### Semantic

Example:

Changing the meaning of:

```text
score
```

Requires migration consideration.

### Breaking

Example:

Removing:

```text
photos
videos
```

or changing identity semantics.

Requires a major schema-version change.

---

## 28. Privacy Considerations

Trip Manifest may contain:

* GPS coordinates
* capture timestamps
* descriptions of people
* inferred locations
* travel patterns

Therefore it should be treated as potentially sensitive project data.

Logs must not dump the complete manifest unnecessarily.

Cloud AI providers should receive only the media or metadata necessary for the requested operation.

---

## 29. Example Lifecycle

Initial analyzer output:

```json
{
  "id": "photo-abc123",
  "path": "Photos/IMG_1001.jpg",
  "score": null,
  "selected": false,
  "scene_id": null,
  "tags": [],
  "description": null,
  "objects": [],
  "emotion": null
}
```

After Vision:

```json
{
  "id": "photo-abc123",
  "path": "Photos/IMG_1001.jpg",
  "score": null,
  "selected": false,
  "scene_id": null,
  "tags": [
    "street",
    "night",
    "seoul"
  ],
  "description": "Night street scene with illuminated storefronts",
  "objects": [
    "buildings",
    "signs",
    "people"
  ],
  "emotion": "energetic"
}
```

After scoring and selection:

```json
{
  "id": "photo-abc123",
  "path": "Photos/IMG_1001.jpg",
  "score": 0.87,
  "selected": true,
  "scene_id": "scene-night-001",
  "tags": [
    "street",
    "night",
    "seoul"
  ],
  "description": "Night street scene with illuminated storefronts",
  "objects": [
    "buildings",
    "signs",
    "people"
  ],
  "emotion": "energetic"
}
```

This illustrates progressive enrichment without changing media identity.

---

## 30. Current Implementation Compatibility

Sprint 2 currently generates:

```text
output/analysis.json
output/trip_manifest.json
```

from the same analyzer result without rescanning the trip.

This behavior is valid and must be preserved until a deliberate output-project migration is implemented.

The future architecture may move artifacts to:

```text
output/<trip-name>/
```

but that migration is outside the scope of this specification.

---

## 31. Quality Gates

A Trip Manifest implementation must not be approved if it:

1. regenerates media IDs unpredictably
2. mixes photos and videos into one collection without an architecture change
3. stores raw AI-provider objects as canonical data
4. allows modules to overwrite unrelated state
5. embeds FFmpeg commands as the editorial data model
6. silently accepts dangling media or scene references
7. requires a complete source rescan for every downstream operation
8. stores secrets or API keys
9. removes Schema 1.0 fields without migration handling

---

## 32. Baseline Decision

For AI Travel Reel Generator V1:

> `trip_manifest.json` is the durable, inspectable and progressively enriched representation of a travel project.

`analysis.json` records what exists.

`trip_manifest.json` records what the system understands and decides.

`reel_plan.json` records what the renderer should execute.

These responsibilities must remain distinct.
# Creative Direction ownership

`creative_direction` is additive Director-owned state. Events invalidate it and all downstream editorial state. Direction invalidates only Selection, media selection markers, Story, Reel Plan, and Render.
# Adaptive Creative Direction fields

`creative_direction.duration_strategy` additively persists mode, minimum/preferred/resolved/maximum
seconds, flexibility, shared safe-shot bounds, and deterministic rationale codes. The media budget
retains legacy shot keys and adds editorial/final targets plus the minimum quality threshold.

`music_analysis` is optional and versioned. It contains immutable source/cache identity, detected
audio facts, confidence-qualified musical inference, duration alignment, and Story mapping.
Changing it invalidates only music-aware planning and rendering state.

`music_selection` is optional, versioned Director/Story-dependent state. It records the deterministic
selection profile, compact per-candidate sub-scores, selected track ID and score, rationale, top
alternatives, and validation/errors. Full beat and energy arrays remain in the selected
`music_analysis` and fingerprint cache rather than being duplicated. Recorded metadata readiness
is not a legal conclusion. Upstream media understanding is not invalidated by a music change.
# Music arrangement contract

`music_selection` additively records strategy type/score, single and multi candidates, winner, alternatives, decision margin/reasons, and validation. `music_arrangement` is the canonical multi-track timing contract: exact segments, transitions, global sync anchors, feasibility, complexity penalty, and assembly status. `music_analysis` remains the backward-compatible canonical single-track analysis and is not used to impersonate a multi-track arrangement.

# Visual template contracts

Manifest version 1.8 additively permits `template_definition` and `visual_plan`. The definition records reusable presentation grammar. Visual Plan records exact duration, resolved blocks, shot ownership, event/phase mappings, normalized layers, semantic motion/transitions, design intent, beat metadata, and validation. A Reel Plan change removes both fields and Render; a template-only change removes Render without touching upstream artifacts.
# Sprint 11.2a resolved layouts

After `layout-plan`, every `visual_plan.blocks[]` contains an additive `resolved_layout` version 1.0. It records a deterministic strategy, normalized composition safe area, solid background token, overlap policy, and one traceable spatial slot for every shot already owned by that block. Layout regeneration preserves all upstream editorial and media-analysis state and invalidates only stale `render` state.
# Sprint 11.2c canonical source dimensions

Canonical `photos[]` and `videos[]` own optional `width`, `height`, and
`orientation`. Width and height are positive integer DISPLAY-ORIENTED ORIGINAL
SOURCE PIXEL DIMENSIONS, before resizing, cropping, layout fitting, or Vision
preprocessing. Orientation is `portrait` when height > width, `landscape` when
width > height, and `square` when equal. This previously reserved field is not
an EXIF numeric tag. Layout retains its independent near-square aspect tolerance.

Consumers resolve dimensions by `media_id`; Selection, Story, Reel Plan, and
Visual Plan need no copies. Old records with absent/null fields remain valid;
unrecoverable dimensions continue to use Layout's unknown fallback.

Run `python -m travel_reel.cli enrich-media-metadata <trip_folder> --config configs/default.yaml`
to enrich an existing manifest without Analyzer or Vision. The config argument
is accepted for CLI consistency; extraction has no configurable policy.
The command probes original sources and atomically persists changed facts.
It preserves IDs, Vision/cache metadata, scores, Events, Creative Direction,
Selection, Story, Music, Reel Plan, template definition, and semantic Visual Blocks.
Only changed width/height invalidates `visual_plan.blocks[].resolved_layout`
and removes `render` state. Existing output media files are not deleted; they
must be regarded as stale. Template grouping does not depend on these dimensions,
so run `layout-plan` explicitly afterward; `template-plan` is not required.

Existing Reel Plan is preserved. A future explicit replan may produce different
framing decisions after canonical dimensions become available.

The command reports `known` (valid dimensions after enrichment), `enriched`
(successfully changed records), `unchanged` (successful identical probes), and
`failed` (per-record failures, with ID/path/reason). The last three counts partition
attempted records; known may include failed probes with valid retained metadata.
Failure never replaces valid metadata with null. An unchanged rerun does not
write or invalidate newly resolved layouts/render state. Source bytes and Vision
cache identity are unchanged. This is an additive optional contract, not a global
mandatory-field or cache-version migration.
# Sprint 11.3a additive Motion contract

Manifest 1.10 adds optional `visual_plan.blocks[].resolved_motion` version 1.0.
Tracks reference resolved slot IDs and carry block-normalized endpoint keyframes,
never duplicated absolute timing or geometry. Existing dimension-less or motion-less
records remain loadable. Motion planning requires valid resolved layouts and
inherited layer visibility. See [Motion Engine](motion-engine.md) for the schema,
controlled strategy vocabulary, transform order, and invalidation semantics.

## Sprint 11.4b-a Typography foundation

Overlay owns an internal Typography subsystem. `overlay-plan` preserves upstream
contracts and optionally attaches `resolved_typography` version 1.0 to each text
Overlay. `resolved_overlay` stays version 1.0; actual typography persistence advances
Manifest to 1.12. Older records without typography remain valid. Font identity is
SHA-256 plus collection face and logical ID, never an authoritative machine path.
Whole-string cmap coverage precedes Pillow/FreeType single-line measurement.
Preferred placement is not collision-certified; `validation.safe` does not imply
full static/Motion collision safety. Font/content/profile/backend changes require
re-resolution and invalidate render metadata when output changes. Renderer remains
deferred. See [Overlay/Typography Engine](overlay-typography-engine.md).

## Sprint 11.4b-b measured text layout

Manifest 1.13 adds optional `resolved_typography.measured_layout` with policy
`measured_lines.v1`. Overlay and Typography remain v1.0. The child owns display
lines, fitted size, normalized baselines/boxes and container-fit evidence;
legacy top-level single-line metrics retain their original meaning. Content stays
unchanged. Bounded CJK/Latin wrapping, readable fitting, conservative ellipsis,
and omission happen inside the existing preferred container. Media/Motion/Overlay
collision safety and Renderer execution remain deferred. Old 1.12 records load
and may be re-resolved using only `overlay-plan`. See the
[typography specification](overlay-typography-engine.md).

## Sprint 11.4b-c placement persistence

Manifest 1.14 persists `resolved_overlay.version = "1.1"` and its required
`placement_resolution.version = "1.0"`. Typography/Layout/Motion remain 1.0.
The placement child records policy versions, canvas-normalized coordinates, the
design canvas, a canonical dependency fingerprint, explicit geometric safety scope,
and ordered preferred/alternate/omitted decisions. Source overlays remain editorial
trace, including omissions. Only the decision-selected placement/Typography is
renderable; preferred decisions reference existing fields, alternates embed their
isolated candidate fields, and omitted decisions have no selected authority.
Legacy 1.13/Overlay 1.0 loads without Placement. The approved overlay-plan stage
upgrades deterministically, validates before atomic write, and invalidates only
downstream render state. See the [authority contract](overlay-typography-engine.md).


## Manifest 1.15: Overlay minimum-gap admission

Overlay 1.2 requires both the unchanged `placement_resolution` 1.0 child and a
`density_admission` child (version 1.0, policy `overlay_minimum_gap.v1`, fixed
`minimum_gap_seconds: 0.5`). It records ordered admitted/suppressed/not_eligible
source decisions and a full-reel dependency fingerprint. Density is post-Placement;
it never changes source evidence, Placement decisions, visibility or upstream timing.
Equality at the minimum gap passes. Final consumers use
`overlay.final_eligible_overlay`, not Placement projection alone. Legacy Overlay
1.0/1.1 loading remains supported. See the Overlay/Typography specification for
exact numeric, validation, authority and migration semantics.
