# Music & Beat Intelligence

Sprint 10 analyzes only explicit, user-supplied local audio. MP3, M4A/AAC, WAV, and FLAC are
normalized by FFmpeg to a temporary mono PCM WAV; originals are read-only and temporary data is
removed on every exit path. No music is downloaded or generated.

The versioned `music_analysis` contract separates detected facts (fingerprint, decoded duration,
sample rate, channel count, relative RMS) from heuristic inference (tempo, beat grid, accents,
phrases, structure, and sync anchors). Downbeats are never claimed by the current analyzer.
Low-confidence tempo may retain a tempo estimate and ambiguity label while omitting the beat grid.

Analysis is cached independently from Vision by source fingerprint, schema/analyzer versions, and
DSP parameters. Editorial fields are recomputed from cached facts so current Story and Creative
Direction remain authoritative. A changed music identity invalidates only Reel Plan and Render.

Duration negotiation searches phrase endings and resolving anchors only inside the Director's
flexibility, duration envelope, and safe-shot bounds. Story phases map monotonically to ordered
musical phrases, with highlight preferring nearby high-energy material and closing preferring the
final available phrase.

Planner alignment is hierarchical: macro-section and Event boundaries first, then style-spaced
beat cuts. Cinematic work is phrase-oriented; beat montage permits denser alignment. Every snap
must preserve the adjacent photo/video duration bounds, total duration, Story order, and Event
continuity. The contract exposes density, peak, accent, and breathing evidence for Sprint 11; it
does not implement visual templates.

Sprint 10.1 adds a compliant local-library layer above this analyzer. Candidate source facts and
heuristics remain in the fingerprinted analysis cache; `music_selection` contains only the
Director/Story profile, compact compatibility scores, reasons, alternatives, and selected track
identity. A library scan never performs network activity. License/source metadata is recorded user
input, audio properties are detected facts, structure is confidence-qualified inference, and the
final ranking is an editorial decision.
# Sprint 10.2 tempo interpretation

Detected tempo remains a source fact. Editorial effective tempo and half/double-time provenance are additive fields; inferred confidence never exceeds detected confidence. Double-time sync subdivisions are heuristic timing aids, not downbeats. See [Multi-Track Music Arrangement](multi-track-music-arrangement.md).
