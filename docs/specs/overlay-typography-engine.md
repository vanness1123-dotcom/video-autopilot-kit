# Overlay / Typography Engine

Sprint 11.4a defines a deterministic, static, renderer-independent text overlay contract.

Story owns narrative meaning; Reel Planner owns absolute timing; Template owns visual grammar; Layout owns media geometry; Motion owns media/card movement. Overlay resolves approved persisted text, visibility, placement intent, and semantic typography. Its internal Typography subsystem resolves local font identity, coverage, and single-line metrics. Renderer execution remains deferred.

## Contract

Each `visual_plan.blocks[]` may contain `resolved_overlay` with `version: "1.0"`, `overlays`, and `selection_reasons`. An overlay has a stable ID, one explicit block or slot target, `time_space: "block_normalized"`, a half-open visibility interval, final authoritative `content.text`, source provenance, normalized placement, semantic style tokens, z-order, and validation metadata. Source is provenance only; Renderer never re-resolves it.

Supported types are `title`, `location_label`, `section_label`, `caption`, `closing_title`, and `closing_subtitle`. `title_card` and `closing_card` remain Template/Layout block types; Overlay only fills their text.

## Sources and policy

Text is selected deterministically from persisted `story.title`, Story/Reel Plan section names, event labels, landmark names, and concise Vision descriptions. Strings are trimmed and redundant whitespace collapsed while preserving Unicode and punctuation. Event underscores may become spaces; semantics are not rewritten. Type-specific length limits cause fallback or omission. Empty overlays are valid and preferred to unsafe or invented content. No AI, translation, or prose generation is performed.

## Timing, placement, and safety

Visibility uses normalized block time, `0 <= start < end <= 1`, and never changes upstream timing. Slot-targeted overlays also remain inside inherited visual-layer timing. Placement uses normalized `x`, `y`, `width`, and `height` inside the existing `resolved_layout.safe_area`; regions are limited to `title_safe`, `upper_safe`, `center_safe`, `lower_safe`, and `canvas`. Placement remains an estimated/preferred text container, not measured text geometry. Existing `validation.safe` describes only the implemented basic bounds/exclusion checks, never full static or Motion collision certification.

Style uses semantic font roles, weights, size classes, alignment, line-height and letter-spacing classes, case policy, max lines, opacity, and background treatment. No authoritative font path is persisted. Traditional Chinese, English, mixed text, numerals, and punctuation remain unchanged.

## Determinism and invalidation

Pure resolution deep-copies inputs and uses stable candidate ordering, IDs, and tie-breaks. Persistence is atomic and advances the additive manifest version to `1.11`. Old manifests without overlays remain loadable; unsupported overlay versions fail explicitly. Overlay changes invalidate render state only. Story/text changes invalidate Overlay and Render; Template, Layout, Motion, and dimension changes invalidate downstream Overlay state through the existing dependency chain.

## Deferred work

11.4b adds exact typography metrics, font resolution, CJK measurement, comprehensive collision handling, and Motion swept-envelope collision. 11.4c adds overlay-local animation, optional Beat alignment, and refined density/repetition policies. Renderer integration remains a later execution sprint.

## Sprint 11.4b-a: single-line typography foundation

`overlay-plan` validates Layout and Motion with their existing validators, resolves
Overlay, validates globally unique Overlay IDs, then attaches optional
`resolved_typography.version = "1.0"`. Overlay remains version 1.0. Actual typography
persistence advances Manifest to 1.12; old manifests remain loadable. No font for
an eligible string is an explicit failure before atomic persistence. Empty Overlay
plans need no font. Identical reruns preserve bytes and valid render metadata.
Changed typography invalidates render metadata only.

Typography does not choose or rewrite content. `lines` is exactly `[content.text]`.
Whole-overlay font fallback requires every distinct codepoint, including spaces,
to map through the selected face's best Unicode cmap to a nonzero glyph other than
`.notdef`. No character is silently ignored. Combining marks, controls, bidi,
variation selectors, emoji sequences, Arabic, Thai, and Indic are explicitly
unsupported. Bounded support covers horizontal Han (basic/extension A/compatibility),
basic Latin/Latin-1, numerals, and common CJK/full-width punctuation. A cmap mapping
proves nominal coverage, not comprehensive OpenType shaping.

### Local font profile and identity

The narrowly scoped `requirements-typography.txt` pins the existing Pillow and
approved fontTools versions without migrating repository packaging. fontTools is
used only to inspect TTFont/TTCollection metadata and cmap; fonts are never saved,
subsetted, copied, installed, downloaded, or redistributed. Pillow BASIC/FreeType
measures the same immutable byte snapshot and explicit face index. Family/style
must agree between the two libraries. Variable fonts are rejected in this phase.

Optional `typography.font_profile` points to a local JSON array (relative to config).
Each entry has `logical_font_id`, `path`, `face_index`, and `weight` (`regular`/`bold`).
Relative font paths resolve against that JSON file. Explicit user candidates precede
Windows candidates; medium maps to regular and semibold to bold. The deterministic
Windows list uses Segoe UI, Arial, JhengHei (including its UI face), MingLiU/PMingLiU,
and YaHei when present. No OS enumeration order is used. Other platforms require
explicit local candidates. `typography.system_fonts: false` disables system fallback.
A TTC identity is the full collection SHA-256 plus selected face index; each face
has its own coverage check. Local paths remain transient.

### Metrics contract and units

The declared design canvas defaults to 1080x1920. Size profile
`single_line_sizes.v1` maps display/large/medium/small/micro to 96/72/52/40/32 reference
pixels respectively, scaled with design height and rounded once. There is no fit or
shrinking ladder. `resolved_font_size` is in design pixels; `line_spacing` is zero.
Only unchanged case, normal letter spacing, and compact line-height intent are
supported by this initial metrics resolver.

The child stores design_canvas, logical_font_id, font_identity (SHA-256, face index,
family/style), metrics_backend (Pillow/FreeType/fontTools versions, BASIC layout,
Unicode-cmap coverage), font_profile version/fingerprint, size profile/version,
requested size class, resolved size, lines, metrics, and dependency_fingerprint.
Metrics use a left-baseline origin and normalized canvas units: advance and ink
left/right divide by design width; ink top/bottom, ascent, descent, baseline_offset,
and line_height divide by design height. Ink overhang and negative ink top are
preserved. Baseline offset equals ascent; line height equals ascent plus descent.
These metrics may exceed the preferred placement box. They do not certify fit.

Validation rejects malformed contracts, bool/nonfinite numerics, invalid SHA/index,
invalid extents, inconsistent lines/baselines, and stale input fingerprints. Coverage
evidence requires `complete_unicode_cmap`; `collision_checked` is explicitly false.
Structural loading does not require local font files. Optional live validation
re-resolves identity, coverage, and metrics against a TypographyResolver, detecting
fabricated/stale metrics. Future execution must verify its font environment.

Dependency SHA-256 covers exact content, consumed style, font/size profile versions,
ordered candidate identity, selected font bytes/face, backend versions, and canvas.
Canonical serialization excludes local absolute paths, render state, timestamps,
Layout/Motion geometry (not consumed by metrics), and filesystem enumeration order.
A resolution snapshots each font once per invocation. No persistent font cache is
needed. Cross-machine replay requires matching font bytes and backend versions;
font substitution requires explicit re-resolution.

Measured wrapping, CJK line breaking, fitting, ellipsis, alternate placements, and
full static/Motion/overlay collision remain later 11.4b work. Animation and Beat-aware
Overlay remain 11.4c. No rasterization or Renderer changes are included.

## Sprint 11.4b-b: measured text inside the preferred container

Typography v1.0 gains the optional `measured_layout` child with policy
`measured_lines.v1`. Overlay stays v1.0; manifests with measured layout advance to
1.13. Existing v1.12 single-line records still validate without local fonts and
can be re-resolved by `overlay-plan`. No upstream stage is rerun.

### Additive semantics and Renderer handoff

The original Typography fields (`lines`, `resolved_font_size`, `metrics`, and
`line_spacing`) retain their 11.4b-a meaning: original unwrapped text measured at
its preferred size. They are not the display layout. When `measured_layout` exists,
its `lines`, `resolved_font_size`, and positioned geometry are the display-layout
authority. This avoids silently changing frozen field semantics. `content.text`
remains the editorial authority even when permitted ellipsis changes presentation.

The child records policy versions, requested/resolved font sizes, size step, fit
scale/reason, max_lines, alignment, minimum size, ellipsis flag, retained source
end, preferred_container, per-line source spans/text/advance, relative ink bounds,
canvas baseline_x/baseline_y, canvas ink_box/advance_box, ascent/descent/line_height,
line_spacing, union resolved_text_bounds, union layout_bounds, dependency fingerprint,
and explicit container-fit evidence. Source spans use Unicode codepoint offsets,
end-exclusive. All geometry and vertical metrics are normalized by the corresponding
canvas axis. Font sizes remain design pixels. Horizontal alignment uses measured
advance plus ink overhang, never character count. The first baseline is container
top plus ascent; subsequent baselines add font ascent+descent and a 0.15 font-size
pixel gap. Only top-anchored line stacking is resolved; there is no new vertical
alignment vocabulary. No background plate geometry is generated.

The preferred container is never moved. Conversion multiplies normalized x/width
by design width and y/height by design height, retaining floating-point precision.
Only font sizes are rounded (Python ties-to-even); no geometry rounding occurs.
Both ink and advance boxes must fit the container; negative ink overhang is included.
Measured ink and advance unions are separate. This guarantees text-container fit,
NOT media, slot, Motion, other Overlay, platform UI, or background-plate safety.

### Bounded break and fitting policy

The existing size-class mapping remains 96/72/52/40/32 reference pixels. Fitting
tries 100%, 95%, 90%, 85% of the preferred size (deduplicated integer sizes), with
full wrapping attempted at each step before smaller sizes. Readability floors at
1920 design height are 52px for title/closing_title and 32px for other types,
scaled with canvas height and rounded upward. A requested size already below its
floor is omitted, never enlarged or silently accepted.

Type defaults: title/location_label/caption/closing_title/closing_subtitle allow
up to two lines; section_label allows one. Existing style.max_lines is authoritative
when stricter. One line wins whenever it fits. Otherwise enumerate legal two-line
breaks; rank by a penalty for a line shorter than 25% of its partner, normalized
width imbalance, then source break index. Balanced wrapping at preferred size is
therefore preferred over a smaller single line. No token-level hyphenation exists.
Latin words stay whole. Break opportunities occur at whitespace or next to Han
characters, subject to punctuation restrictions; NBSP is not a whitespace break.
Mixed Latin runs remain intact. Wrapping removes only layout-edge whitespace;
internal source whitespace remains exact and source offsets explain every break.
Supported source scripts and controls remain bounded as in 11.4b-a.

`bounded_cjk.v1` forbids line endings with opening brackets/quotes including
??????? and line starts with closing brackets/quotes or ???????.
Common ASCII brackets and punctuation are also covered. This is not comprehensive
Unicode Line Breaking or Japanese kinsoku conformance.

Only section_label, caption, and closing_subtitle may use U+2026 ellipsis. It is
attempted at the smallest allowed step only after all full-text attempts fail.
The retained prefix must end at a legal token/character boundary and retain at
least 70% of non-whitespace source characters. Long Latin tokens are not split.
The selected whole-overlay face must cover both original text and U+2026; the
result is remeasured and display codepoints are checked again. There is no
per-line or per-glyph fallback. Titles and venue/location labels never ellipsize.
No suitable fit raises a specific fit failure; orchestration removes that Overlay
and appends a concise `typography_omitted:<id>:<reason>` selection reason. It does
not compensate with new Overlay candidates. Missing fonts/dependencies, malformed
contracts, and unsupported scripts remain explicit errors before atomic write.

Search is bounded to 256 source codepoints, four size steps, at most 255 two-line
breaks per attempt, and at most 255 retained-prefix candidates for ellipsis.
Typical short one-line labels return immediately. No media I/O, network, shaping
service, font download, rasterization, or Renderer execution is performed.

### Validation, dependencies and scope

Validation recomputes source-span composition, legal punctuation/breaks, retention,
line-count/size policy, baseline/alignment equations, box unions, container bounds,
and line non-overlap. Bool and nonfinite numerics fail. Malformed or stale policy,
geometry, and dependency values are rejected rather than repaired. Live validation
also re-resolves the selected font bytes, coverage, and measured values; structural
loading alone cannot prove a font's actual cmap or metrics without that font.

The child dependency fingerprint covers the original metrics dependency, exact
text/type, preferred container, alignment, max_lines, size floors, and versioned
line-breaking/punctuation/fitting/spacing/ellipsis policy. The parent fingerprint
also incorporates this child dependency. Render-only changes are irrelevant;
text/container/style/font/backend/policy changes require re-resolution. Changed
output invalidates render metadata; identical reruns preserve manifest bytes.

Layout/Motion collision, alternate placement, title/subtitle collision stacking,
platform safe areas and plate geometry remain deferred to 11.4b-c. Animation,
Beat-aware presentation and Renderer execution remain deferred. System fonts are
read locally and never redistributed.

## Sprint 11.4b-c: authoritative placement resolution

`overlay-plan` now persists Overlay 1.1 and Manifest 1.14. Layout, Motion,
Typography and `measured_lines.v1` retain their accepted semantics. Overlay intent
generation remains a transient v1.0 input; final v1.1 records require the
`placement_resolution` v1.0 child (`placement_collision.v1`,
`placement_candidates.v1`, `canvas_normalized`, explicit design canvas).

Every editorial source remains in `overlays`, even when omitted. Decisions are
one-to-one in that stable order. Original `placement` and `resolved_typography`
remain preferred intent/measurement. `preferred` decisions reference those fields
without duplicate payloads. `alternate` decisions own `selected_placement` and
isolated `selected_typography`, measured against the candidate's aligned projection.
`omitted` decisions have no selected candidate or rendering authority.
`placement_contract.selected_overlay` returns the isolated authoritative final
projection, or None for omission. Consumers must not render the editorial list
without consulting decisions. Renderer execution is not implemented here.

The pipeline measures preferred text without dropping fit failures, resolves
placement, validates the full result, advances the manifest and writes atomically.
Successful earlier reservations constrain later overlays only during co-visibility.
No later-to-earlier feedback or replacement text selection occurs. Missing fonts
and malformed contracts fail before persistence; legitimate fit/collision failures
can produce traced omission. Preferred fitting failures retain no fabricated metrics.

Compact decisions include the selected candidate ID, preferred-placement digest,
authority references, static/Motion results, outcome/reason, bounded candidate and
evaluation counts, and a rejection histogram. Each rejected candidate contributes
its first rejection reason, so the histogram sums to `rejected_count`. Candidate
polygons and full traces are not persisted. A capped candidate pool can be marked
truncated even when the first candidate succeeds; `evaluated_count` distinguishes
actual evaluation from the available pool.

`geometric_scope.v1` lists canvas/design bounds, protected slots, co-visible text,
supported continuous Motion sweeps and required-host containment as checked.
Faces, people, landmarks, salient subjects, unmeasured decorations, platform UI,
rounded-corner free space and plates are explicitly unassessed. A selected result
uses `geometric_policy_pass`, never a semantic safety claim. Legacy `validation.safe`
is retained only as preferred Overlay metadata; Typography collision flags remain
false because Placement owns the collision evidence.

The canonical dependency digest covers ordered editorial input, preferred metrics,
slot geometry/roles/clip/fit, design margins, Motion tracks/easing, inherited windows,
consumed media dimensions, canvas and policy versions. It excludes previous decisions,
render state, debug/runtime/timestamps and absolute font paths. Changed dependencies
reject stale results; upstream invalidation removes the enclosing resolved Overlay.
Changed final output invalidates render metadata; identical reruns preserve bytes.
Legacy v1.0 input remains readable and deterministically upgrades on overlay-plan.

Structural validation requires no local font access and checks authority, exact
schemas, geometry, current collision evidence, IDs/counts and dependencies. Optional
`validate_live_placement` replays font-backed selection to additionally verify
ranking and omission decisions. Neither form adds subject detection or rendering.


## Sprint 11.4c Phase B: minimum-gap admission

Manifest 1.15 / Overlay 1.2 adds `density_admission` to each resolved Overlay
contract after Placement. Placement Resolution 1.0, Typography, Layout, Motion,
and `measured_lines.v1` are unchanged. Renderer execution remains deferred.

The child has exactly `version: "1.0"`, `policy_version: "overlay_minimum_gap.v1"`,
`minimum_gap_seconds: 0.5`, `dependency_fingerprint`, and `decisions`.
The half-second gap is a small conservative versioned default, not an empirically
optimal editorial threshold. This version accepts only that fixed value.

Traversal follows the validated chronological block list, then each block's source
Overlay list (also Placement decision order). Source order breaks within-block ties;
no reordering or replacement occurs. For block [B,E) and visibility [u,v), derive
[B+u(E-B), B+v(E-B)). Arithmetic uses exact fractions of the persisted numbers'
decimal spellings, without epsilon, rounding, frame snapping, or ambient decimal
precision. Admit the first geometrically selected overlay. Thereafter admit iff
start >= last admitted end + 0.5 seconds. Equality passes. Only admission updates
the remembered end. Geometric omissions and density suppression never extend it.

Each source has one ordered decision with exactly `overlay_id`, `state`, `reason`:
- `admitted` / `first_selected` or `minimum_gap_satisfied`;
- `suppressed` / `minimum_gap_not_met`;
- `not_eligible` / `placement_omitted` (not a density suppression).

The enclosing block supplies block identity. Every block, including empty blocks,
stores the same full-reel dependency SHA-256 over canonical policy and ordered block
IDs/bounds, exact source records, Placement decisions and Placement dependency hashes.
Prior density output, render state, timestamps and unrelated runtime data are excluded.
Validation replays the whole reel, checks exact child/decision schemas and ordered
identities, and rejects stale cross-block decisions or mixed legacy/1.2 contracts.
Structural loading requires no fonts. Source text, IDs, visibility, typography,
geometry, Placement decisions and all upstream timing are preserved.

`overlay.final_eligible_overlay(manifest, plan, overlay_id)` validates the complete
plan and returns an isolated selected projection only when finally eligible, or None
for either omission/suppression. Placement's `selected_overlay` remains geometric
projection only; it is not final eligibility for Overlay 1.2. Legacy 1.1 retains
Placement-only eligibility. Legacy 1.0 loads as before but this accessor rejects it
until Placement is resolved. Unknown IDs and malformed/stale contracts fail explicitly.

The pipeline regenerates source intent, resolves Placement, then resolves admission.
A changed result invalidates render state; identical output does not write the manifest
and preserves valid render metadata. Migration advances versions once; subsequent
identical runs preserve bytes. No duration/visibility edits, reading floors, animation,
beat alignment, text replacement, repetition changes or Renderer integration are added.
