# Creative Director

Sprint 8 inserts deterministic editorial reasoning between Event Intelligence and Selection. It reads the manifest inventory, persisted Vision observations, scores, and Events; it never invokes those stages or external inference.

The `creative_direction` payload owns `version`, `director_version`, `provider`, `style`, `content_profile`, `pacing`, `media_budget`, `event_strategy`, `template_strategy`, `music_strategy`, `rationale`, and `validation`. The provider protocol permits a future LLM implementation without changing downstream contracts.

AUTO style selection is stable and evidence-based. Dense, diverse large inventories can support `beat_montage`; active or motion-rich inventories can support `dynamic_travel_highlight`; multi-Event, human or diverse trips can support `travel_story`; quieter/smaller inventories use `cinematic_travel`. An explicit controlled style overrides AUTO.

The media budget starts with duration divided by the style's editorial shot duration, adjusts for measured diversity, enforces feasible Event representation, and clamps to usable scored media. Event allocation combines strongest and mean score, capped size contribution, media-type/category diversity, persisted evidence, people, landmark and activity evidence. Repeated allocation has diminishing returns, so Event size alone cannot dominate.

Template and music strategies are intent metadata only. They contain no frames, beats, downloads, transitions, or rendering effects.

Run `python -m travel_reel.cli direct <trip_folder> --config configs/default.yaml` after `events`. Re-running Events invalidates Direction and all later stages. Re-running Director preserves inventory, Vision, scores, and Events while invalidating Selection, Story, Plan, Render, and media-level selection state.
# Sprint 9 adaptive duration

Duration is an editorial output, jointly resolved with the shot budget. `duration_strategy`
records the configured mode and envelope, preferred and resolved seconds, safe shot bounds,
flexibility, and deterministic evidence codes. Fixed mode remains available for explicit jobs.

`music_strategy` reserves energy, beat-driven intent, approximate duration, flexibility, and
hook/build/peak/release structure for Sprint 10. `template_strategy` remains intent-only for
Sprint 11: primary family, burst permission, continuity, breathing, and beat-sync intensity.

Music may move the resolved editorial duration only within `flexibility_seconds`, the adaptive
envelope, and shared safe-shot bounds. The original editorial duration and explained delta remain
persisted in Music Intelligence.
# Dynamic template handoff

`template_strategy` remains high-level Director intent. Sprint 11.1 maps that intent and the selected built-in definition into presentation blocks after Reel Planning; Director does not own resolved geometry or renderer instructions.
