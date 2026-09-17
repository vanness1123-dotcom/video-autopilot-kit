# Dynamic Template Engine

## Responsibility boundary

Story decides what the narrative contains. Reel Planner decides when each editorial shot appears. The Template Engine decides how those immutable planned units are presented. Renderer remains the deterministic executor. Sprint 11.1 produces contracts only; the legacy Renderer neither requires nor executes `visual_plan`.

Template definitions are versioned, renderer-independent dictionaries. They contain semantic block types, normalized geometry, motion and transition intent, abstract typography tokens, generic decoration tokens, sequencing preferences, and adaptation rules. They never contain FFmpeg graphs or proprietary assets.

## Resolution

The resolver consumes existing `creative_direction`, `story`, event IDs propagated into Reel Plan shots, and global music anchors already present in `reel_plan.music_intelligence`. It performs no event grouping or music analysis. It groups consecutive planned shots without changing their editorial timing, prefers same-event multi-media blocks, varies complex blocks, and resolves all shots exactly once.

Cross-event grouping is selective rather than forbidden. Adjacent shots must remain in the same Story phase and every crossed event boundary must meet a deterministic editorial-affinity threshold using only persisted media evidence: travel category, activity, scene type, mood, landmark name, tag overlap, and capture-time proximity. Same-event groups receive the strongest affinity. Cross-event groups persist their score and evidence reasons; phase adjacency alone contributes no semantic affinity. This consumes Event Intelligence identity without recreating or overriding event grouping.

Layout choice uses media-count compatibility, phase preference, pacing, existing beat support, affinity, and recent block history. Recent-use penalties allow three-up, grid, collage, and layered-card definitions to become competitive without quotas. `beat_montage` additionally requires fast/dynamic pacing, a compatible multi-shot run, and at least two existing anchors inside its interval.

Duration is inherited from `reel_plan.actual_duration_seconds`; no reference duration exists. The same template therefore resolves 30-, 56-, and 90-second plans by consuming their shot sequence rather than repeating a fixed timeline. Each resolved layer records both immutable editorial timing and visual-layer timing so future simultaneous presentation remains explicit.

Validation rejects unsupported versions, blocks, motion and transition intents; invalid or non-finite normalized geometry; unknown, duplicate, or missing shot ownership; invalid phases and timing; non-deterministic order; and duration disagreement.

Template definition or sequencing changes invalidate `visual_plan` and `render` only. Changes to upstream editorial timing invalidate them as downstream artifacts. Vision, Scores, Events, Selection, Story, and cached music facts are never invalidated by template-only changes.

## Semantic vocabularies

Blocks: `fullscreen_media`, `hero_media`, `two_up`, `three_up`, `grid`, `collage`, `layered_cards`, `beat_montage`, `title_card`, `closing_card`.

Motion: `none`, `push_in`, `pull_out`, directional pans, `slide_in`, `slide_out`, `scale`, `translate`, `fade`, and `pop`. Timing is normalized from 0 to 1 with an abstract easing and optional beat alignment intent.

Transitions: `cut`, `dissolve`, `fade`, `flash`, `slide`, `zoom`, and `mask_reveal`. These are future renderer intents, not current Renderer capability claims.

Typography uses semantic roles and abstract tokens such as `travel_handwritten`, `clean_sans`, `editorial_serif`, and `compact_label`. Decorations use generic sticker, doodle, frame, tape, paper, line, and shape categories.

## Sprint 11.2a static layout handoff

`template-plan` continues to own semantic block selection. The separate `layout-plan` stage consumes that Visual Plan and embeds a versioned `resolved_layout` in each block. The static Layout Engine owns normalized slots, deterministic strategy identity, safe-area policy, background intent, fit intent, clipping intent, and z-order. Existing block ownership and timing remain immutable. Animation, overlays, and FFmpeg execution remain later-stage responsibilities.
