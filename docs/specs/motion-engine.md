# Motion Engine — Sprint 11.3c

Motion owns how existing elements move, never editorial scheduling, grouping,
base geometry, source playback, or visibility. `motion-plan <trip_folder>
--config configs/default.yaml` consumes persisted canonical dimensions, Reel Plan,
Visual Plan, and valid resolved Layout. It performs no probing, decoding, AI,
music analysis, or rendering. Renderer integration remains Sprint 11.7.

## Contract

Each `visual_plan.blocks[].resolved_motion` contains `version: "1.0"`,
`time_space: "block_normalized"`, `tracks`, and string `selection_reasons`.
Each track has `target_slot_id`, `space`, `strategy`, and `keyframes`.
There is exactly one track per owned resolved slot in this base version (thus
at most one per target/space pair). Targets join template layers through shot_id,
not template slot names. No media IDs, source paths, base geometry, or absolute
timestamps are duplicated.

Keyframes contain `t` and `transform`. Every non-final keyframe also contains
`easing_to_next`, either `linear` or `smoothstep`. Smoothstep is 3q²−2q³ for
segment-local q in [0,1]. Both curves are monotone and non-overshooting.
All channels in a segment MUST use the same easing scalar. Content/hold strategies
use two endpoints; card strategies use three keyframes in this same schema.

## Time and visibility

u = (timeline time − block start) / (block end − block start).
The first and last keyframes cover the inherited visual-layer window, normalized into the
block. Evaluation is gated by that upstream half-open [start,end) window; the
right keyframe is the limiting endpoint, not permission for another visible frame.
Motion never extends layers, retains previous cards, or creates cumulative
reveals. Spatially overlapping cards can still have sequential visibility.
Editorial timing must agree with Reel Plan; explicit upstream visual timing is
preserved. Relocation requires re-resolution to validate inherited inputs.

## Transform spaces and order

`media_content` transforms fitted source imagery inside the fixed slot clip.
`slot` transforms the whole card relative to resolved base geometry.
Vocabulary: translate_x, translate_y, uniform scale, opacity. Translation units
are fractions of base slot width/height, pivot is the center, and opacity multiplies
Layout opacity. Scale about center precedes translation; source fit → content
transform → clip → slot transform → base placement/static rotation. Layout
fit, z-order, clipping, and static rotation remain authoritative. Animated rotation
and renderer-specific expressions are prohibited.

Content tracks retain opacity 1. Slot tracks use small scale changes and opacity
in [0.85,1]; they do not translate in 11.3b. Identity hold is valid in either space.
Card animation fades within the inherited window without making a layer entirely
invisible or extending its playback interval.

## Strategies and eligibility

`hold.v1`: identity at both endpoints, universal safe fallback.
`slow_push_in.v1`: scale 1 to 1+e, without translation.
`slow_pull_out.v1`: scale 1+e to 1, without translation.
`pan_horizontal_left.v1` / `pan_horizontal_right.v1`: fitted imagery translates
left/right in slot-local coordinates; this is image direction, not camera direction.
`pan_vertical_up.v1` / `pan_vertical_down.v1`: corresponding vertical translation.
`subtle_drift.v1`: very small diagonal translation plus scale 1+0.5e to 1+0.8e.

Content motion requires known positive canonical dimensions, a photo, cover fit,
and at least 0.75 seconds. Videos never receive content pan, drift, push or pull.
Contain keeps its fitted composition; it is eligible for safe slot behavior only.
Unknown dimensions conservatively permit hold only, with an explicit reason.
Template motion is an input hint, never copied endpoints. `motion.type=none` and
`motion.enabled=false` are hard identity disables.

## Duration and Director adaptation

The real 56-second benchmark has 31 photo windows of 1.000–1.754 seconds. The old
two-second threshold prevented all photo motion. The following internal bounds
allow smaller excursions across that observed range; they are conservative design
limits, not perceptual measurements or a target active-motion percentage.

| Class | Visibility duration d | Base scale excursion e |
| --- | --- | --- |
| extremely_short | d < 0.75s | 0; hold only |
| short | 0.75 <= d < 2s | 0.010 + 0.015*(d-0.75)/1.25 |
| medium | 2 <= d < 6s | 0.025 + 0.015*(d-2)/4 |
| long | d >= 6s | min(0.060, 0.040 + 0.005*(d-6)) |

Director phase pacing overrides overall pacing; exploration/experience use `body`
when no exact phase exists. Style supplies only a missing-pacing fallback.
Explicit factors: cinematic 0.70, balanced 1.00, dynamic 0.90, fast 0.75. Closing
multiplies excursion by 0.65; non-primary layered cards by 0.50. Excursion is
rounded to six decimals. Global content scale remains in [1,1.06]. Fast, short
shots consequently receive smaller movement, not larger movement.

## Crop slack and complete-path proof

Current Layout is 9:16. With source aspect A and normalized slot width w/height h,
physical slot aspect B=(w*9/16)/h. Cover-fitted dimensions in slot units are
Fw=max(1,A/B), Fh=max(1,B/A). At content scale s, horizontal and vertical slack are
Sx=(s*Fw-1)/2 and Sy=(s*Fh-1)/2. Coverage requires |tx|<=Sx and |ty|<=Sy.

Pans require natural scale-1 slack >=0.005 on the chosen axis. Endpoint magnitude
is min(0.5e, 0.6*natural_slack, 0.025), and must be >=0.0025. Scale remains 1;
no zoom is manufactured solely to enable a pan. Matching-aspect imagery therefore
cannot pan. Source orientation is not a direction selector: a portrait source can
have horizontal slack in a narrower portrait slot.

Drift uses endpoint magnitudes min(0.12e, half the slack at initial scale, 0.006)
on each axis, with a minimum meaningful magnitude of 0.0005. It may use the small
slack introduced by its conservative initial zoom. It never becomes a large pan.

Every scale/translation channel shares one monotone segment parameter q. The
coverage inequalities are affine halfspaces in those channels. Each intermediate
transform is a convex combination of consecutive keyframes, so validating ALL
keyframes proves the full segment. Independently eased channels, overshoot, and
animated rotation would invalidate that proof and are prohibited.

## Card behavior and swept safety

`card_enter.v1`: small scale/fade from 1-k, opacity .85 to identity, then hold.
`card_exit.v1`: identity hold, then scale/fade to 1-k, opacity .85 at layer end.
Here k=min(0.012,0.4e). The settle/exit phase lasts min(25% of visibility,0.3s).
`card_emphasis.v1`: identity -> scale 1+k at midpoint -> identity, opacity 1.

Entrance/exit are limited to hero, primary layered-card, and closing families.
Two-up/three-up/grid/collage may use bounded emphasis but no card flying.
Non-primary layered cards have no slot animation and half-strength content motion,
with a stronger hold preference. Beat montage keeps sequential replacement and
content-only candidates until 11.3c. Videos default to hold with a high suitability
score; a suitable card hint/phase can select safe slot behavior. Trims, timestamps,
source playback and rate never change.

Card corners are evaluated in physical canvas-height units, incorporating static
Layout rotation. Fixed-angle corners are affine in uniform scale/translation, so
their segment sweep is bounded by endpoint corner envelopes. ALL keyframes are
checked against canvas/safe area, including the middle emphasis keyframe. Identity
content/hold never enlarges base geometry and remains a fallback when an existing
rotated card has insufficient margin for slot animation.

For co-visible slots with prohibited/temporal-replacement overlap policy, swept
AABBs must not intersect. This is deliberately conservative: it can reject paths
whose envelopes intersect at different moments. Sequential half-open windows do
not acquire a collision merely because their spatial envelopes overlap.
Intentional-overlap families use an upper bound on swept AABB intersection divided
by a lower bound on actual rectangular card area to reject >=90% occlusion risk. Static z-order
never changes. Geometry is never edited to make a candidate eligible.

## Deterministic suitability and repetition

Generate candidates, filter geometry, then score. Base scores: hold 20 (video 38),
push 30, pull 29, pan 28+min(natural_slack,.1)*30, drift 27; card enter 24, exit 23,
emphasis 25. Matching template hints add 8. Hook/highlight favor push (+2); closing
favors pull (+4), exit (+6), and hold (+6). Hook favors entrance (+5); dynamic/fast
pacing adds 4 to entrance. Primary cards favor emphasis (+5). Beat montage adds
4 to hold; background layered cards add 12 to hold. These are suitability scores,
not distribution quotas. See code for the controlled hint-to-strategy mapping.

The preceding three selected tracks form bounded history. Each matching family
subtracts 4 and each exact strategy/direction subtracts another 2, capped implicitly
at 18 total. Hold is never penalized. Pan directions share their axis family.
Comparable safe alternatives can win, while a stronger composition preference
survives the penalty. Stable lexical strategy-name ties have no random/UUID/hash/
clock input. Concise reasons persist duration class, pacing, safety evidence,
matching intent, applied repetition penalty and final score.

Base candidate decisions do not read music or beat anchors. No media decoding or source
probing is performed. No focal-point or subject-preservation guarantees are made.

## Beat-aware refinement

Sprint 11.3c consumes only `reel_plan.music_intelligence.sync_anchors[]` when that
collection is explicitly persisted in reel-timeline time. The Motion resolver does
not read `music_analysis.beats`, phrase timestamps, or track-local anchors. Existing
arrangement mapping is authoritative; no audio timing is reconstructed. Each usable
anchor is normalized internally to `time_seconds`, `provenance`, and `confidence`.
Malformed, non-finite, negative, out-of-duration, empty-provenance, and unknown
provenance entries are ignored. Duplicate times are rounded to milliseconds and
retain the deterministic highest-ranked value: supported provenance first, then
confidence, then lexical provenance. The original anchor collection is never copied
into blocks or tracks.

Only `detected_beat`, `heuristic_accent`, `opening_accent`, and
`final_resolving_beat` with confidence >=0.5 are eligible. A subdivision is not
treated as a beat or downbeat. Confidence is trust in the persisted detection, not
musical energy. Phrase semantics remain unknown unless a future persisted contract
explicitly carries them. Anchors inside a transition whose mapping is ambiguous
must be omitted upstream; Motion does not infer a replacement mapping.

Beat refinement is optional and layer-local. For an existing active content track,
one progression keyframe may be inserted at a trusted interior anchor. Existing
card enter/exit/emphasis tracks may move their one interior settle/peak point to the
anchor. The anchor is converted with `u=(anchor_time−block_start)/block_duration`
and must remain inside the inherited normalized layer window. Endpoints, visibility,
strategy, and transforms remain unchanged. No repeated pulse, pan restart, or
additional micro-keyframes is generated. At most one anchor is consumed per track.

Anchors must have at least 0.15 seconds from each absolute layer boundary, must be
at least 20% inside the normalized layer span, and are not considered for windows
shorter than 1.5 seconds. These rules protect the benchmark's short photo windows.
Hold tracks never consume an anchor. Missing music, missing `sync_anchors`, source-
local beats only, malformed anchors, low confidence, unsupported provenance, and
boundary-near anchors preserve ordinary 11.3b Motion byte-for-byte.

Director and template intent still rank strategy safety first. `beat_driven`,
beat-sync intent, pacing, phase, and style may be used only as bounded preferences;
11.3c does not alter their contracts. Closing remains restrained. Beat alignment
cannot override cover crop slack, swept card bounds, duration, or repetition rules.

When a track consumes an anchor it may carry this minimal evidence extension:

```json
"beat_alignment": {
  "anchor_time_seconds": 3.0,
  "normalized_time": 0.5,
  "provenance": "detected_beat",
  "confidence": 0.9
}
```

The evidence must match an eligible persisted anchor and an actual keyframe. Tracks
without alignment omit the field. This remains Motion consumer evidence; there is
no `motion.music_analysis`, `motion.beats`, or `motion.phrases` contract. Manifest
version remains 1.10 and Motion version remains 1.0 because the extension is
optional and backward-compatible. If consumed anchors change with timing/Layout
unchanged, Motion and its downstream overlays/render state are stale; Layout,
Template, and Reel Plan remain valid. Changes to irrelevant source-local music
metadata do not affect Motion.

Beat-aware output is a planning contract only. Renderer does not execute it yet, so
metadata cannot establish audiovisual synchronization quality.

## Persistence and validation

Pure resolution deep-copies inputs; orchestration persists atomically and advances
manifest version additively to 1.10. Old manifests without Motion remain loadable;
Motion validation rejects unknown versions. Missing/invalid Layout is actionable:
Run 'layout-plan' first.

Validation checks exact target coverage, inherited windows, keyframe order and
endpoints, controlled fields/easing/spaces/strategies, finite numbers excluding
booleans, strategy-specific transform bounds, and unchanged upstream contracts.
No Motion strategy may override source timing, grouping, Layout, or visibility.

Changed Motion invalidates render and reserved Motion-dependent `overlay_plan` /
block `resolved_overlay` state, preserving template typography/decorations.
Changed dimensions invalidate Layout, Motion and downstream state. Changed Layout
removes affected block Motion. Changed Template semantic state removes Layout and
Motion. Identical template/layout/enrichment/motion reruns preserve valid downstream
state. Render media files are never deleted by planning; invalidated output metadata
must not be mistaken for a newly rendered result.

## Deferred

11.3d owns hardening. Animated rotation,
simultaneous/cumulative reveal without upstream visibility, speed changes, source
tracking, and rendered visual-quality claims remain outside this sprint. Renderer
does not execute these contracts yet; benchmark assessment is planning-only.

Manifest 1.10 / Motion envelope version 1.0 remain unchanged: strategy vocabulary
and three-keyframe tracks extend the existing schema. Explicit motion-plan reruns
replace old resolved tracks under the new suitability and adaptive bounds; old
motion-less manifests still load. Superseded active plans may require re-resolution
to satisfy the tighter duration-dependent bounds. No automatic upstream replan.
