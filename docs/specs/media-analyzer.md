# AI Travel Reel Generator — Media Analyzer Specification

**Document Version:** 1.0
**Status:** Baseline
**Component:** Media Analyzer
**Related Documents:** `system-architecture.md`, `trip-manifest.md`

---

## 1. Purpose

The Media Analyzer is the deterministic ingestion component of AI Travel Reel Generator.

Its responsibility is to inspect a travel-media folder and produce reliable, reproducible source facts describing all supported photos and videos.

The Media Analyzer does not decide whether media is good, interesting, representative, or suitable for the final Reel.

Its job is to answer:

> What media exists, and what objective properties can be extracted from it?

---

## 2. Current Implementation Baseline

Sprint 1 introduced the executable command:

```text
travel-reel analyze <trip-folder>
```

During local development, the equivalent command may be executed as:

```powershell
$env:PYTHONPATH="src"
python -m travel_reel.cli analyze examples\Korea2026
```

The current implementation generates:

```text
output/analysis.json
output/trip_manifest.json
```

from a single source scan.

The Trip Manifest must not trigger a second scan.

---

## 3. Responsibilities

The Media Analyzer is responsible for:

* recursively scanning a trip folder
* detecting supported photos
* detecting supported videos
* normalizing file extensions
* collecting file sizes
* extracting capture timestamps when available
* extracting EXIF metadata when available
* extracting GPS metadata when available
* extracting video creation time when available
* collecting folder-level statistics
* assigning deterministic media IDs
* providing data required to initialize Trip Manifest
* reporting unsupported or unreadable media safely

---

## 4. Non-Responsibilities

The Media Analyzer must not:

* perform semantic Vision analysis
* rank media
* detect emotional value
* determine composition quality using AI
* select final Reel content
* assign story importance
* create scenes
* generate story text
* build a Reel timeline
* execute FFmpeg rendering
* invoke cloud LLM or Vision providers

These responsibilities belong to later components.

---

## 5. Input Contract

Primary input:

```text
<trip-folder>
```

Recommended structure:

```text
Trip/
├── Photos/
└── Videos/
```

However, the analyzer must recursively scan the provided root and must not require all media to be placed exactly in these two directories.

Example:

```text
Korea2026/
├── Day1/
│   ├── IMG_001.jpg
│   └── VID_001.mp4
├── Day2/
│   ├── Cafe/
│   └── LotteWorld/
└── Photos/
```

Recursive media discovery must still work.

---

## 6. Supported Photo Formats

Baseline supported extensions:

```text
.jpg
.jpeg
.png
.heic
.webp
```

Extension matching must be case-insensitive.

Examples:

```text
IMG001.JPG
IMG002.jpeg
IMG003.HEIC
```

must be recognized.

---

## 7. Supported Video Formats

Baseline supported extensions:

```text
.mp4
.mov
.m4v
.avi
```

Extension matching must be case-insensitive.

Additional formats may be introduced later only after explicit compatibility validation.

---

## 8. Recursive Discovery

The analyzer must scan recursively from the requested trip root.

Conceptually:

```text
Trip Root
   ↓
recursive traversal
   ↓
supported media detection
   ↓
normalized media records
```

Non-media files must be ignored unless needed for another explicitly defined feature.

Examples to ignore:

```text
.txt
.md
.json
.db
.tmp
```

The analyzer should not fail because unrelated files exist in the source folder.

---

## 9. Media Classification

Every detected file must be classified as:

```text
photo
```

or:

```text
video
```

Classification must be deterministic and based on supported media type rules.

The analyzer must not use AI to determine file type.

---

## 10. File Metadata

Every recognized media object should provide source facts including, where available:

```text
relative path
file size
capture time
GPS
```

Future enrichment should include:

```text
filename
width
height
orientation
camera make
camera model
```

for photos.

For videos:

```text
duration
width
height
orientation
fps
codec
creation time
```

---

## 11. Relative Paths

Canonical media references stored in project artifacts should prefer paths relative to the trip root.

Example:

```text
Photos/IMG_1001.jpg
```

instead of using an absolute Windows path as the media identity.

Absolute source-folder location may remain at project level.

Benefits:

* project portability
* cleaner JSON
* deterministic IDs
* easier debugging
* reduced machine-specific coupling

---

## 12. Capture Time

For photos, preferred timestamp source:

```text
EXIF DateTimeOriginal
```

Fallbacks may be introduced later.

For videos, preferred timestamp source should come from reliable media metadata such as creation time where available.

Timestamp extraction must not fabricate a value when reliable metadata does not exist.

Missing timestamps must remain:

```json
null
```

rather than using arbitrary current time.

---

## 13. Date Range

Trip date range should be derived from valid captured-at values.

Example:

```text
earliest valid capture date
~
latest valid capture date
```

Files without a valid capture timestamp must not distort the trip date range.

If no reliable timestamp exists:

```text
Unavailable
```

must be reported.

---

## 14. GPS Extraction

When available, GPS should be represented using normalized decimal coordinates.

Example:

```json
{
  "latitude": 37.5665,
  "longitude": 126.978
}
```

The analyzer must not infer GPS from:

* filename
* folder name
* AI image understanding
* assumed itinerary

No GPS means:

```json
null
```

The CLI-level trip summary may report:

```text
GPS : Available
```

when at least one media item contains valid GPS.

Otherwise:

```text
GPS : Unavailable
```

---

## 15. Camera Metadata

Future analyzer versions should support deterministic extraction of:

```text
camera_make
camera_model
```

where available.

Examples:

```text
Apple
iPhone
Sony
Canon
Samsung
```

Camera metadata remains a source fact and must not be generated by AI.

---

## 16. Image Dimensions

Future image records should include:

```json
{
  "width": 4032,
  "height": 3024
}
```

Dimensions should reflect the effective display orientation where possible.

The implementation must clearly define whether EXIF rotation is applied before calculating orientation.

---

## 17. Orientation

Recommended normalized values:

```text
portrait
landscape
square
unknown
```

Possible deterministic rule:

```text
height > width  → portrait
width > height  → landscape
width == height → square
```

Rotation metadata must be handled correctly before final orientation classification.

Orientation is particularly important for vertical Reel suitability.

---

## 18. Video Metadata

Video metadata should be obtained using reliable deterministic tooling.

Preferred mechanism:

```text
FFprobe
```

Relevant future fields include:

```text
duration_seconds
width
height
fps
codec
rotation
orientation
creation_time
```

The analyzer should reuse existing FFmpeg/FFprobe infrastructure in the repository when appropriate rather than implementing redundant probing logic.

---

## 19. Deterministic Media IDs

Every photo and video must have a stable ID.

Properties:

* deterministic
* collision-resistant within a trip
* independent of list order
* independent of AI state
* stable across repeated analysis of unchanged media

A suitable implementation may derive IDs from normalized relative path plus stable source metadata.

The exact hashing strategy is an implementation detail, but behavior must satisfy the contract.

Changing:

```text
score
selected
tags
scene_id
story
```

must never change the media ID.

---

## 20. Duplicate Handling

The Media Analyzer does not decide editorial duplicates.

However, it may later expose deterministic duplicate signals such as:

```text
exact file hash
same file size
same capture timestamp
```

Editorial near-duplicate detection belongs to:

```text
Scoring System
Media Selector
```

Examples of editorial duplicates:

* five nearly identical selfies
* burst photos
* repeated landmark angles

These require later logic and are not Analyzer responsibilities.

---

## 21. Unsupported Media

Unsupported file types must be ignored or reported as warnings.

They must not terminate an otherwise valid trip scan.

Example:

```text
Korea2026/
├── Photos/
├── Videos/
├── itinerary.pdf
└── notes.txt
```

The PDF and TXT files must not prevent travel-media analysis.

---

## 22. Corrupted Media

Unreadable or corrupted media must be handled explicitly.

Recommended behavior:

```text
detect file
   ↓
metadata extraction fails
   ↓
record warning
   ↓
continue processing remaining files
```

The pipeline should not fail the entire trip because one source file is damaged unless the error makes project integrity impossible.

Future records may contain:

```json
{
  "status": "metadata_error",
  "warnings": []
}
```

---

## 23. Analyzer Output Model

The Analyzer should produce an internal structured result rather than directly coupling all business logic to JSON output.

Conceptual model:

```text
TripAnalysis
├── trip metadata
├── photos
├── videos
├── folder statistics
└── warnings
```

Serialization is handled by the application/pipeline layer.

This keeps Analyzer logic reusable.

---

## 24. Analysis JSON

`analysis.json` is the objective analyzer artifact.

Its characteristics:

* reproducible
* deterministic where source metadata permits
* independent of AI providers
* does not contain editorial decisions

It should remain useful for:

* debugging
* audit
* source inventory
* regression testing

---

## 25. Trip Manifest Initialization

The same Analyzer result initializes:

```text
trip_manifest.json
```

The analyzer must not rescan the trip to create the manifest.

Expected flow:

```text
scan once
   ↓
TripAnalysis
   ├── analysis.json
   └── trip_manifest.json
```

This behavior already exists in Sprint 2 and must be preserved.

---

## 26. CLI Behavior

Baseline command:

```text
travel-reel analyze <trip-folder>
```

Expected output format should remain concise and operational.

Example:

```text
Scanning Korea2026...

Photos : 202
Videos : 37
GPS : Unavailable
Date Range :
2026-07-24
~
2026-07-29

Output:
output\analysis.json
```

Exact wording may evolve, but critical summary information must remain available.

---

## 27. Exit Behavior

Recommended future CLI exit codes:

```text
0 = success
1 = invalid input
2 = analyzer failure
3 = output serialization failure
```

Detailed exit-code implementation is not mandatory for the existing Sprint 1 baseline but is recommended before V1 release.

---

## 28. Empty Project Behavior

An empty valid directory must not crash the analyzer.

Example result:

```text
Photos : 0
Videos : 0
GPS : Unavailable
Date Range : Unavailable
```

This behavior was validated during Sprint 1 and should remain supported.

---

## 29. Performance Expectations

Media discovery should be efficient for typical travel projects containing:

```text
hundreds to several thousand files
```

The Analyzer should avoid:

* decoding full videos unnecessarily
* performing AI requests
* generating full-resolution thumbnails during baseline scan
* repeated FFprobe calls for the same unchanged file where caching is available later

The initial deterministic inventory should remain relatively lightweight.

---

## 30. Caching Strategy

Caching is optional for the current baseline but should be supported in future evolution.

Potential cache key inputs:

```text
relative path
file size
modification time
media ID
```

If a source file is unchanged, expensive metadata probing should eventually be reusable.

---

## 31. Logging

Analyzer logs should support operational debugging.

Recommended data:

```text
trip root
scan start
scan end
files discovered
photos detected
videos detected
metadata warnings
unreadable files
output locations
elapsed time
```

Logs must not unnecessarily expose complete GPS information.

---

## 32. Error Boundaries

Potential analyzer error categories:

```text
TripFolderNotFound
TripFolderAccessError
MediaMetadataError
FFprobeError
SerializationError
```

Individual metadata extraction errors should generally degrade gracefully.

Trip-level errors such as a nonexistent source folder should fail explicitly.

---

## 33. Testing Requirements

The Analyzer must have automated coverage for:

* recursive scanning
* supported photo extensions
* supported video extensions
* case-insensitive extension detection
* empty directories
* mixed unrelated files
* metadata extraction
* GPS extraction where test data permits
* video creation-time extraction
* deterministic media IDs
* analysis JSON generation
* Trip Manifest generation without rescanning

Synthetic or temporary fixtures should be preferred over committing large travel media into unit tests.

---

## 34. Real-World Validation

In addition to unit tests, the analyzer must be validated against real travel media before major releases.

A real-world validation should confirm:

```text
photo count
video count
date range
GPS behavior
output generation
no crash on mixed real media
```

Real-world tests complement unit tests because phone and camera metadata vary substantially.

---

## 35. Current Validated Baseline

The current implementation has been validated on the Korea2026 example project.

Observed result:

```text
Photos : 202
Videos : 37
GPS : Unavailable
Date Range :
2026-07-24
~
2026-07-29
```

This baseline is useful for regression validation.

A future Analyzer change that unexpectedly produces materially different inventory counts must be investigated.

---

## 36. Privacy

The Analyzer may read sensitive metadata such as:

```text
GPS
timestamps
camera identifiers
folder names
```

Therefore:

* source data should stay local by default
* Analyzer itself must not upload media
* logs should avoid unnecessary sensitive detail
* future cloud processing must occur in later provider layers, not inside Analyzer

---

## 37. Dependency Rules

Media Analyzer may depend on:

```text
Python standard library
metadata libraries
existing FFmpeg/FFprobe utilities
internal domain/model definitions
```

It must not depend on:

```text
OpenAI SDK
Gemini SDK
LLM providers
Story Director
Media Selector
Renderer business logic
```

This preserves deterministic ingestion.

---

## 38. Future Enhancements

Potential post-baseline improvements:

* camera make/model extraction
* exact dimensions
* normalized orientation
* complete video probe metadata
* HDR detection
* exact duplicate hash
* metadata cache
* source-change detection
* analyzer performance metrics
* thumbnail index generation
* contact sheet generation

These enhancements must preserve the Analyzer responsibility boundary.

---

## 39. Quality Gates

A Media Analyzer change must not be approved if it:

1. performs semantic AI analysis
2. performs editorial selection
3. modifies source media
4. requires cloud access
5. changes IDs unpredictably
6. rescans unnecessarily when constructing both output artifacts
7. fabricates missing metadata
8. crashes the entire analysis because one media file is unreadable
9. couples Analyzer behavior directly to rendering logic
10. changes the validated source inventory without explanation

---

## 40. Baseline Decision

The Media Analyzer is a deterministic source-ingestion component.

Its contract is:

> Discover the travel media once, extract trustworthy source facts, and make those facts available to every later stage without editorial interpretation.

AI begins after the Analyzer boundary.
