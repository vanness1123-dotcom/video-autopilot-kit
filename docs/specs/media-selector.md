# AI Travel Reel Generator — Media Selector Specification

**Document Version:** 1.0

> Sprint 7.5 selection consumes Event membership, preserves representatives across distinct Events, and limits duplicate suppression to members of the same known Event.
**Status:** Baseline
**Component:** Media Selector
**Related Documents:** `system-architecture.md`, `trip-manifest.md`, `vision-provider.md`, `scoring-system.md`

---

## 1. Purpose

The Media Selector converts the full analyzed travel-media library into a compact, diverse, story-ready candidate set for the final Reel.

Its responsibility is to answer:

> Which photos and videos should remain eligible for the Reel, and why?

The Media Selector consumes previously computed media facts, Vision observations, and scores.

It does not render video and does not generate the final story.

---

## 2. Architecture Role

The Media Selector sits between Scoring and Story Direction.

```text
Media Analyzer
      ↓
Vision Provider
      ↓
Scoring System
      ↓
Media Selector
      ↓
Story Director
      ↓
Reel Planner
```

The Selector reduces the candidate space while preserving diversity and story coverage.

---

## 3. Core Design Principle

Selection must not equal:

```text
sort by score descending
take top N
```

That approach can produce poor Reels such as:

* too many selfies
* too many photos from one landmark
* no transportation
* no food
* no night scene
* no videos
* repeated burst images
* poor chronological coverage

The Selector therefore performs:

> quality filtering + diversity control + travel coverage + media balance

---

## 4. Responsibilities

The Media Selector is responsible for:

* applying eligibility rules
* ranking media
* suppressing duplicates
* preserving scene diversity
* preserving temporal coverage
* balancing photos and videos
* preserving major travel categories
* preventing one location or scene from dominating
* producing a candidate pool
* marking selected media in Trip Manifest
* recording concise selection reasons

---

## 5. Non-Responsibilities

The Media Selector must not:

* perform Vision analysis
* recalculate metadata
* create the final travel story
* assign final shot durations
* generate subtitles
* execute FFmpeg
* decide transitions
* modify source media

---

## 6. Input Contract

The Selector consumes media records containing, where available:

```text
media ID
media type
capture time
GPS/location hints
Vision description
tags
travel category
scene type
score
score breakdown
duplicate signals
orientation
duration for videos
```

Missing optional data must not cause automatic failure.

---

## 7. Output Contract

The Selector updates selection-related state.

Conceptually:

```json
{
  "selected": true,
  "selection_rank": 3,
  "selection_reason": [
    "strong story value",
    "unique night scene",
    "high travel relevance"
  ]
}
```

The baseline Sprint 2 Boolean field remains:

```json
"selected": false
```

Future additive fields may include:

```text
selection_rank
selection_reason
selection_group
```

---

## 8. Candidate Pool

The Selector does not necessarily choose only the exact final Reel shots.

It should first produce a slightly larger candidate pool.

Example:

```text
239 source media
↓
50–70 viable media
↓
Story Director / Planner
↓
15–25 final shots
```

Exact values are configuration-driven.

This provides flexibility to downstream storytelling.

---

## 9. Hard Eligibility Filtering

Media may be excluded before ranking if it is clearly unusable.

Examples:

* corrupted media
* exact duplicates
* extreme blur
* unreadable file
* invalid video duration
* zero usable frames
* explicit user exclusion

Hard exclusions must include a reason.

---

## 10. Soft Filtering

Lower-quality media may remain available with reduced priority.

Examples:

* weak composition
* poor vertical crop
* redundant scene
* low travel relevance
* weak story value

Soft filtering is preferred when a media item may still serve a unique narrative purpose.

---

## 11. Diversity Requirement

Diversity is a first-class selection requirement.

The candidate set should represent multiple dimensions:

```text
time
location
travel category
scene type
media type
visual mood
people vs environment
day vs night
```

A high-quality but repetitive set is not considered a good selection.

---

## 12. Temporal Coverage

The Selector should avoid selecting only one portion of the trip.

Where timestamps are available, candidate selection should cover:

```text
beginning
middle
ending
```

and, for multi-day trips:

```text
multiple days
```

Temporal coverage is particularly important for chronological travel storytelling.

---

## 13. Location Coverage

Where GPS or location inference is available, the Selector should preserve representative location diversity.

Example failure:

```text
25 selected media
23 from Lotte World
2 from everywhere else
```

unless the trip itself was predominantly a Lotte World visit.

Location diversity should reflect actual source distribution and story importance.

---

## 14. Travel Category Coverage

Recommended categories include:

```text
arrival
transportation
landmark
food
cafe
shopping
street
nature
cityscape
nightlife
accommodation
theme_park
activity
portrait
selfie
group
detail
transition
other
```

The Selector should prefer broad representative coverage rather than maximizing one category.

---

## 15. Category Quotas

V1 may use soft category quotas.

Example conceptual policy:

```text
selfies ≤ 25% of candidate pool
food ≤ 20%
landmarks ≤ 30%
videos ≥ minimum target when usable
```

These are not absolute product rules.

Exact values belong in configuration and must be validated against real travel collections.

---

## 16. Photo / Video Balance

The Reel should not become a slideshow if strong video exists.

Likewise, poor videos should not be selected simply to satisfy a quota.

A balanced strategy should:

* prefer usable motion footage where it adds value
* retain high-quality photos
* avoid video starvation
* avoid low-quality video padding

---

## 17. Recommended MVP Media Mix

For a 40-second Reel, a reasonable planning target is approximately:

```text
15–25 total shots
```

Candidate selection may retain more.

A possible final mix:

```text
40–60% video shots
40–60% photo shots
```

This is a starting assumption, not a fixed requirement.

---

## 18. Duplicate Suppression

Duplicate suppression is mandatory.

Near-duplicate groups may include:

* burst photos
* repeated selfies
* same landmark angle
* multiple nearly identical food photos

The Selector should generally retain:

```text
best representative
+
optional alternate
```

rather than the entire group.

---

## 19. Duplicate Group Strategy

Conceptually:

```text
duplicate cluster
      ↓
rank members
      ↓
keep highest-quality representative
      ↓
optionally keep one alternate if story value differs
```

The duplicate penalty from Scoring System informs this decision.

---

## 20. Scene Saturation Control

The Selector must prevent one scene from monopolizing the candidate set.

Example:

```text
Lotte World = 80 source items
Han River = 8 source items
Cafe = 5 source items
```

Selection should not simply mirror raw source volume.

Scene importance should be normalized.

---

## 21. Source Volume Bias

Users often take more photos at exciting locations.

Raw count therefore does not equal story importance.

The Selector should reduce source-volume bias.

Otherwise:

```text
most photographed place = entire Reel
```

This is undesirable.

---

## 22. Score Is Necessary but Not Sufficient

A score represents media strength.

Selection represents editorial usefulness.

Example:

```text
Photo A score = 0.95
Photo B score = 0.87
```

Photo B may still be selected over Photo A if it provides:

* unique location coverage
* a missing travel category
* an important story transition
* different visual mood

---

## 23. Selection Utility

Conceptually, selection utility can combine:

```text
base score
+
diversity bonus
+
scene coverage bonus
+
temporal coverage bonus
+
video-motion bonus
-
duplicate penalty
-
scene saturation penalty
```

Exact implementation belongs to code and configuration.

---

## 24. Selection Stages

Recommended V1 selection pipeline:

```text
all media
   ↓
hard rejection
   ↓
duplicate grouping
   ↓
score ranking
   ↓
category balancing
   ↓
scene balancing
   ↓
temporal balancing
   ↓
photo/video balancing
   ↓
candidate pool
```

---

## 25. Selection Rank

Selected media should receive a rank or priority.

Example:

```json
{
  "selected": true,
  "selection_rank": 8
}
```

Lower numeric rank may represent higher priority.

Rank semantics must remain consistent.

---

## 26. Selection Reasons

Reasons should be concise and structured.

Examples:

```text
high story value
strong visual quality
unique location
best member of duplicate group
important trip transition
representative food scene
strong motion
night-scene coverage
```

Avoid hidden-chain-of-thought style explanations.

---

## 27. Forced Inclusion

Future user overrides may support:

```text
favorite
force_include
```

Forced inclusion should bypass ordinary ranking unless the media is technically impossible to use.

---

## 28. Forced Exclusion

Future user overrides may support:

```text
force_exclude
```

Forced exclusion always wins.

This is useful when users do not want specific private or undesirable media included.

---

## 29. Scene Availability

The Selector may operate before final semantic scenes are fully created.

In that case, it may use provisional grouping based on:

```text
time proximity
GPS proximity
travel category
Vision similarity
folder structure
```

Final Story scenes belong to Story Director.

---

## 30. Multi-Day Trips

For multi-day trips, the Selector should preserve cross-day coverage.

Example:

```text
Day 1
Day 2
Day 3
Day 4
```

should not become:

```text
90% Day 3
```

unless media quality or trip context strongly justifies it.

---

## 31. Opening and Ending Candidates

The Selector may flag media suitable for:

```text
opening
ending
transition
```

without deciding final story placement.

Examples of opening candidates:

* airport
* airplane
* train departure
* city arrival
* first major establishing shot

Ending candidates:

* night view
* sunset
* departure
* final group shot
* closing cityscape

Final use is decided by Story Director and Planner.

---

## 32. Motion Priority

Video should receive additional consideration when motion communicates an experience better than a still.

Examples:

```text
theme park ride
street crossing
train movement
food cooking
performance
river movement
walking sequence
```

Motion priority must not override poor technical quality.

---

## 33. Portrait / Selfie Balance

Travel Reels benefit from showing the traveler, but excessive selfie selection reduces travel context.

The Selector should prevent face-heavy saturation.

A useful candidate set includes a mixture of:

```text
people
places
food
activity
environment
details
```

---

## 34. Establishing Shots

The Selector should preserve strong establishing shots.

Examples:

* wide city view
* station entrance
* landmark exterior
* street overview
* river landscape

These may have lower emotional scores than selfies but high narrative value.

---

## 35. Detail Shots

Detail media can improve visual rhythm.

Examples:

* food close-up
* ticket
* signage
* coffee
* souvenirs
* architectural detail

The Selector may preserve a limited number of strong detail shots.

---

## 36. Transition Candidates

Some media may be useful primarily as transitions.

Examples:

* train window
* walking feet
* escalator
* street movement
* station signage
* passing scenery

These should not necessarily compete directly with hero shots.

---

## 37. Candidate Roles

Future selector output may support:

```text
hero
support
transition
detail
opening_candidate
ending_candidate
```

One media item may have multiple candidate roles.

These roles help Story Director.

---

## 38. Configuration

Selection behavior should be configuration-driven.

Example:

```yaml
selector:
  candidate_count: 60
  max_selfie_ratio: 0.25
  target_video_ratio: 0.50
  duplicate_similarity_threshold: 0.90
  scene_saturation_limit: 0.30
```

Exact values are subject to validation.

---

## 39. Small Trips

If a trip contains only a small number of usable media items, quotas must degrade gracefully.

Example:

```text
8 photos
2 videos
```

The Selector should not reject useful media simply to satisfy diversity quotas.

---

## 40. Large Trips

For hundreds or thousands of media items, selection should remain efficient.

Possible strategy:

```text
pre-filter
↓
duplicate grouping
↓
top-K per category/scene
↓
global balancing
```

Avoid computationally expensive all-pairs comparisons where better indexing strategies exist.

---

## 41. Determinism

Given:

* same manifest
* same scores
* same selector config
* same selector version

selection should be reproducible.

Any randomness used for creative alternatives must be optional and seeded.

---

## 42. Selector Version

Future implementation should preserve:

```text
selector_version
```

This allows comparison when editorial logic changes.

---

## 43. Manifest Integration

The Selector should enrich existing media entries.

Example:

```json
{
  "id": "photo-abc123",
  "score": 0.89,
  "selected": true,
  "selection_rank": 4,
  "selection_reason": [
    "strong travel relevance",
    "unique scene coverage"
  ]
}
```

Media IDs must remain unchanged.

---

## 44. Validation Rules

Selection output should validate:

* selected IDs exist
* no exact duplicate selected twice
* selection ranks are unique where required
* selected count does not exceed configured candidate limit
* force-excluded media is not selected
* hard-rejected media is not selected

---

## 45. Failure Modes

Common failure modes include:

### Score-only bias

Only globally highest scores survive.

### Scene saturation

One attraction dominates.

### Selfie saturation

Too many portraits.

### Photo-only output

Strong videos ignored.

### Video-padding

Poor videos included merely to meet ratio.

### Timeline gap

Entire days absent.

### Duplicate leakage

Burst photos survive.

### Story starvation

No arrival, transition, or ending candidates remain.

---

## 46. Real-World Validation

The Selector must be evaluated against real trip collections.

Useful metrics include:

```text
candidate count
duplicate rate
scene diversity
day coverage
category coverage
photo/video ratio
human agreement
```

Human review remains important during tuning.

---

## 47. Human Evaluation

For development, compare:

```text
AI candidate set
vs
human preferred set
```

The goal is not perfect overlap.

The goal is:

> Most AI-selected media should feel reasonable and representative.

---

## 48. Testing Requirements

Automated tests should cover:

* hard exclusions
* duplicate suppression
* score ordering
* scene caps
* category balancing
* temporal coverage
* video minimum logic
* small-trip fallback
* user force include/exclude
* deterministic output
* selection-reason serialization

---

## 49. Privacy

Selection occurs locally using already-persisted project state.

It should not require additional cloud Vision calls.

---

## 50. Quality Gates

A Media Selector implementation must not be approved if it:

1. simply selects top-N global scores
2. ignores duplicate clusters
3. ignores scene saturation
4. ignores multi-day coverage
5. consistently starves video
6. forces poor video to meet arbitrary quotas
7. makes selection decisions impossible to inspect
8. re-runs Vision unnecessarily
9. directly renders media
10. modifies source files

---

## 51. Baseline Decision

The Media Selector is a constrained editorial-ranking layer.

Its contract is:

> Reduce the full trip library into a high-quality, diverse, representative and story-ready candidate set.

Selection quality is measured not by whether every chosen item is individually perfect, but by whether the candidate set represents the trip well as a whole.
# Sprint 8 strategy input

Selection consumes the Director's feasible adaptive target, preferred mix intent, and per-Event representation targets while retaining diversity and near-duplicate suppression. It records unmet Event targets instead of selecting duplicates to satisfy a quota.
