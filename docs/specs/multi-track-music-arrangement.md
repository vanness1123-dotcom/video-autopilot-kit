# Multi-Track Music Arrangement

Sprint 10.2 treats decoding, standalone eligibility, arrangement eligibility, and rights metadata as separate contracts. A short track may be `engineering_usable` and `multi_track_eligible` while being `single_track_eligible: false`. Local engineering use never changes `production_ready`; complete source/license metadata is readiness evidence, not a copyright-safety guarantee.

The system does not loop, repeat, synthesize, or AI-extend music. A standalone aligned duration is `null` when the source cannot cover the Director envelope. Arrangement source ranges are bounded by decoded source duration and fingerprints cannot repeat within one candidate.

## Tempo and anchors

`detected_bpm` remains the immutable analyzer fact. Credible detections may expose bounded half-time and double-time candidates with `detected_primary`, `heuristic_half_time`, or `heuristic_double_time` provenance. Director pacing selects `effective_bpm`; inferred confidence is capped below primary confidence. Silence and low-confidence evidence create no inferred tempo. Double-time creates deterministic `heuristic_subdivision` timing anchors between detected beats. These anchors are not claimed as musical downbeats, and no key or harmonic compatibility is claimed.

## Candidate policy

The generator takes only a configured top-compatible pool, enumerates unique two/three-track combinations, and evaluates a bounded deterministic set of orders. Segments prefer phrase/source boundaries and carry exact source and global timeline ranges, story phase mapping, energy role, tempo facts, and compact sync anchors. Adjacent segments use `cut` or bounded `short_crossfade`; crossfade timeline duration is `sum(segment durations) - sum(overlaps)`.

Feasibility is a hard constraint. Strategy scoring covers track editorial scores, effective-tempo and transition continuity, energy progression, ending evidence, story coverage, analysis/metadata evidence, and a configured per-switch complexity penalty. A multi-track strategy wins only if its score exceeds the best single strategy by `multi_track_decision_margin`; otherwise the single is retained. The manifest records the margin and reason.

## Assembly

The selected strategy is assembled to `output/music_arrangement.m4a` with source-local `atrim`, timestamp-resetting `asetpts`, bounded `acrossfade`, and final duration trim. Assembly is atomic and duration-validated. No destructive loudness normalization is applied. FFmpeg failure leaves source files unchanged and prevents a successful assembly claim.
