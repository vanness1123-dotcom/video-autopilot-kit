# Local Music Library

Sprint 10.1 accepts only music already present on the user's machine. It does not search,
scrape, download, or authenticate with music websites. Users remain responsible for obtaining
and using audio under appropriate terms.

## Layout and intake

The configured `music.library_path` contains `tracks/` and `metadata/`. `music-import` validates
the extension, fingerprints the source, copies it into `tracks/` under a content-derived track ID,
verifies the copy, and writes a JSON sidecar. It never modifies or overwrites the source. Duplicate
content resolves to the existing track even when filenames differ. Scanning is deliberately
non-recursive and cannot consume files outside `tracks/`.

Downloaded audio binaries are ignored by Git. Sidecars may be backed up or versioned when they
contain no private data. Metadata fields are factual user records: title, creator, source name and
page, license name and URL, attribution requirement/text, download time, notes, filename, and
fingerprint. Missing values remain null; the system does not infer licensing from a filename.

## Readiness

All decoded tracks are `engineering_usable`. `production_ready` means the required source and
license fields were recorded and any required attribution text is present; it is not a legal or
copyright-safety opinion. Status is one of `verified_metadata`, `incomplete_metadata`, or
`local_only`.

## Ranking

`music-select` derives a deterministic profile from Creative Direction and Story, reuses Music
Intelligence analysis by fingerprint, and ranks unique candidates by duration fit, pacing/tempo,
beat confidence, relative energy movement, Story-arc structure, peak usefulness, ending quality,
beat density, style fit, reliability, and metadata readiness. BPM is deliberately only one input.
The selected analysis is handed directly to Planner; no path copying is required.
# Sprint 10.2 eligibility

Library records distinguish `engineering_usable`, `single_track_eligible`, `multi_track_eligible`, and metadata-only `production_ready`. Short tracks remain reusable arrangement components. The product performs no looping or AI extension, and local-only music is not automatically legally publishable.
