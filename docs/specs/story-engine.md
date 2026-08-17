# AI Travel Reel Generator — Story Engine Specification

**Document Version:** 1.0
**Status:** Baseline
**Component:** Story Engine
**Related Documents:** `system-architecture.md`, `trip-manifest.md`, `vision-provider.md`, `scoring-system.md`, `media-selector.md`

---

## 1. Purpose

The Story Engine transforms a selected set of travel-media candidates into a coherent short-form travel narrative.

Its responsibility is to answer:

> What story should this Reel tell, and what narrative role should each selected memory play?

The Story Engine operates after media analysis, Vision enrichment, scoring, and candidate selection.

It does not render video and does not define exact FFmpeg operations.

---

## 2. Product Goal

The target product is a short vertical travel Reel.

Baseline target:

```text
Duration: approximately 40 seconds
Format: 9:16
Content: photos + videos
Primary domain: personal travel memories
```

The Story Engine should turn a collection of travel media into something that feels intentionally edited rather than randomly assembled.

---

## 3. Architecture Role

```text
Media Analyzer
      ↓
Vision Provider
      ↓
Scoring System
      ↓
Media Selector
      ↓
Story Engine
      ↓
Reel Planner
      ↓
Renderer
```

The Story Engine creates narrative intent.

The Reel Planner converts that intent into executable timing and shot decisions.

---

## 4. Responsibilities

The Story Engine is responsible for:

* determining overall narrative structure
* identifying major trip moments
* grouping candidate media into narrative scenes
* establishing beginning, progression, highlight, and ending
* determining scene order
* assigning narrative roles
* identifying hero moments
* identifying transition moments
* identifying optional detail shots
* generating concise story metadata
* optionally generating short text overlays
* producing structured story output

---

## 5. Non-Responsibilities

The Story Engine must not:

* perform raw media scanning
* perform Vision analysis
* calculate technical quality
* calculate final media scores
* execute FFmpeg
* encode MP4
* decide exact transition implementation
* define frame-level timing
* modify source files

---

## 6. Story Philosophy

The Reel should not simply show:

```text
best photo
best photo
best video
best photo
best video
```

It should create progression.

A useful travel narrative generally contains:

```text
Arrival
   ↓
Exploration
   ↓
Experiences
   ↓
Highlights
   ↓
Closing memory
```

The exact structure may adapt to the available media.

---

## 7. Baseline Narrative Structure

For a general travel Reel, the recommended baseline structure is:

```text
HOOK
 ↓
ARRIVAL / ESTABLISHMENT
 ↓
EXPLORATION
 ↓
EXPERIENCE
 ↓
HIGHLIGHT
 ↓
CLOSING
```

Not every Reel must contain every stage explicitly.

The Story Engine should degrade gracefully based on available material.

---

## 8. Hook

The first few seconds must create immediate visual interest.

Suitable Hook material may include:

* strongest landmark
* dramatic cityscape
* energetic activity
* memorable portrait
* exciting video motion
* iconic travel moment

The Hook does not have to be chronologically first.

---

## 9. Hook vs Chronology

Strict chronological order is not mandatory.

A strong Reel may use:

```text
Highlight teaser
      ↓
Beginning of trip
      ↓
Journey progression
      ↓
Return to highlight
      ↓
Closing
```

This structure can improve short-form engagement.

---

## 10. Arrival / Establishment

Arrival establishes:

```text
Where are we?
What kind of trip is this?
```

Possible media:

* airport
* airplane
* train
* station
* hotel
* city entrance
* street establishing shot
* destination signage

Arrival scenes should remain concise.

---

## 11. Exploration

Exploration communicates movement through the destination.

Possible categories:

* streets
* neighborhoods
* shopping
* markets
* cafes
* transportation
* walking
* city views

This section often provides narrative continuity.

---

## 12. Experiences

Experiences represent what the traveler actually did.

Examples:

* eating
* shopping
* rides
* performances
* attractions
* sightseeing
* cafes
* activities

Experience scenes should favor action and human interest where available.

---

## 13. Highlight

The Highlight is the strongest emotional or visual section.

It may include:

* major attraction
* strongest landmark
* theme park
* night scene
* performance
* dramatic scenery
* memorable personal moment

A Reel may contain more than one highlight, but too many reduce narrative hierarchy.

---

## 14. Closing

The ending should feel intentional.

Suitable closing material:

* night cityscape
* sunset
* final portrait
* departure
* airplane
* train
* distant landscape
* quiet final memory

The ending does not need to explain everything.

It should provide closure.

---

## 15. Narrative Scene

A narrative scene is a group of media representing one coherent story unit.

Conceptual structure:

```json
{
  "scene_id": "scene-003",
  "title": "Hongdae Night",
  "role": "exploration",
  "media_ids": [],
  "summary": "Night exploration through Hongdae streets and shops.",
  "priority": 0.82
}
```

Exact schema may evolve.

---

## 16. Story Roles

Recommended normalized roles:

```text
hook
arrival
establishing
exploration
experience
food
transition
highlight
detail
closing
```

These roles describe narrative purpose rather than Vision category.

---

## 17. Vision Category vs Story Role

These must remain separate.

Example:

```text
Vision category:
theme_park

Story role:
highlight
```

Another:

```text
Vision category:
transportation

Story role:
transition
```

Vision describes what the media contains.

Story Engine decides what it means in the Reel.

---

## 18. Hero Media

Hero media represents major moments.

Examples:

* strongest city view
* iconic landmark
* memorable portrait
* dramatic video
* major activity

Hero media should receive stronger narrative priority.

---

## 19. Supporting Media

Supporting media provides context.

Examples:

```text
street detail
food
shop exterior
station sign
walking shot
ticket
coffee
```

Supporting media helps avoid a Reel composed entirely of hero shots.

---

## 20. Transition Media

Transition media connects scenes.

Examples:

* train movement
* walking
* escalator
* road
* station
* airplane window
* street crossing
* passing scenery

Transition media can improve perceived continuity.

---

## 21. Detail Media

Detail shots provide visual rhythm.

Examples:

```text
food close-up
souvenir
ticket
signage
coffee
architecture
shopping item
```

Detail shots should normally remain short in the final plan.

Exact duration belongs to Reel Planner.

---

## 22. Story Input

The Story Engine consumes selected candidate media with information such as:

```text
media ID
capture time
Vision description
tags
travel category
scene type
emotion
score
score breakdown
selection rank
selection reason
candidate role
```

It should not reopen source files unless required by an explicitly defined future feature.

---

## 23. Story Output

Conceptual output:

```json
{
  "story_version": "1.0",
  "title": "Korea 2026",
  "style": "cinematic-travel",
  "structure": [
    "hook",
    "arrival",
    "exploration",
    "experience",
    "highlight",
    "closing"
  ],
  "scenes": [],
  "text_overlays": [],
  "summary": ""
}
```

This should be stored in the Trip Manifest story section or a compatible derived artifact.

---

## 24. Structured Output Requirement

Story output must be machine-readable.

The canonical result must not be only free-form prose.

Preferred flow:

```text
Selected media
      ↓
Story Engine
      ↓
Structured Story JSON
      ↓
Schema validation
      ↓
Reel Planner
```

---

## 25. AI Role

An LLM is appropriate for Story Engine because narrative organization is semantic and contextual.

The LLM may help determine:

* meaningful grouping
* narrative hierarchy
* story progression
* scene titles
* concise summaries
* optional overlay text

However, it must operate within structured constraints.

---

## 26. Deterministic Context

The Story Engine should receive reliable facts from earlier stages.

It must not independently invent:

* locations
* dates
* activities
* landmark names
* events

If upstream information is uncertain, the story should remain generic rather than fabricate specificity.

---

## 27. Chronological Awareness

Capture timestamps should be used when available.

The Story Engine should understand:

```text
Day 1
Day 2
Day 3
...
```

but may deviate from strict chronology when doing so improves the short-form narrative.

---

## 28. Multi-Day Compression

A 5-day trip cannot be represented equally in 40 seconds.

The Story Engine must compress.

It should prioritize:

```text
representative moments
major changes in place/activity
high-value memories
important transitions
```

rather than allocate equal duration to every day.

---

## 29. Scene Count

For a 40-second Reel, a reasonable story target is approximately:

```text
5–8 narrative scenes
```

This is not equivalent to shot count.

One narrative scene may contain multiple shots.

---

## 30. Shot Count Awareness

The Story Engine may know the target shot budget.

Example:

```text
15–25 final shots
```

but must not assign exact shot durations.

That belongs to Reel Planner.

---

## 31. Pacing Intent

The Story Engine may describe pacing intent.

Normalized values may include:

```text
slow
moderate
fast
dynamic
```

Example:

```json
{
  "scene_id": "scene-004",
  "pacing": "dynamic"
}
```

The Planner converts pacing intent into actual timing.

---

## 32. Emotional Arc

Where suitable, the Story Engine may construct an emotional arc.

Example:

```text
curiosity
  ↓
discovery
  ↓
energy
  ↓
highlight
  ↓
nostalgia
```

This should remain an editorial device rather than psychological inference.

---

## 33. Visual Rhythm

Story ordering should avoid excessive repetition.

Example poor sequence:

```text
selfie
selfie
selfie
portrait
portrait
```

Preferred variation:

```text
cityscape
portrait
street
video activity
food detail
landmark
```

The Story Engine should consider visual rhythm alongside narrative meaning.

---

## 34. Photo / Video Awareness

Story scenes should exploit video where motion matters.

Example:

```text
theme park ride → video preferred
food still life → photo acceptable
train movement → video preferred
portrait → photo acceptable
```

The Story Engine may express preference but must not manufacture missing video.

---

## 35. Opening Strategy

Potential opening strategies:

```text
hero-first
arrival-first
motion-first
landmark-first
portrait-first
```

Recommended MVP default:

```text
hero-first
```

unless media availability suggests otherwise.

---

## 36. Closing Strategy

Potential closing strategies:

```text
departure
night-view
final-portrait
quiet-memory
landscape
```

The closing should contrast or resolve the opening where possible.

---

## 37. Text Overlay

The Story Engine may generate optional concise overlay text.

Examples:

```text
SEOUL
DAY 1
Hongdae Night
Lotte World
Last Night
```

Text should remain short and visually usable.

---

## 38. Overlay Constraints

Overlay text should avoid:

* long paragraphs
* unsupported facts
* excessive emoji
* excessive punctuation
* redundant captions

Recommended length:

```text
1–6 words
```

for most overlays.

---

## 39. Narration

Voice narration is not required for the first Travel Reel MVP.

The architecture may support future narration, but Story Engine V1 should not require TTS or Whisper.

This reduces initial complexity.

---

## 40. Music Awareness

Story Engine may express broad musical pacing intent such as:

```text
calm intro
build
energetic middle
emotional close
```

Actual beat detection, synchronization, and audio mixing belong downstream.

---

## 41. Style Profiles

Future Story Engine versions may support:

```text
cinematic
energetic
luxury
nostalgic
vlog
minimal
```

MVP should start with one strong default travel style rather than attempting many poorly tuned styles.

Recommended default:

```text
cinematic-travel
```

---

## 42. Story Diversity

The Story Engine should avoid stories composed entirely of:

```text
landmarks
selfies
food
shopping
```

unless that category genuinely defines the trip.

A general travel story should usually mix:

```text
place
people
movement
activity
details
```

---

## 43. Story Coherence

A scene transition should ideally have at least one logical connection:

```text
time
location
activity
visual similarity
movement
emotion
```

Random ordering should be avoided.

---

## 44. Scene Priority

Scenes may receive priority:

```text
0.0 – 1.0
```

Priority reflects narrative importance.

It is not the same as individual media score.

Example:

A lower-scoring airport clip may belong to a high-value arrival scene.

---

## 45. Media Reuse

A single media item should normally appear only once in the story.

Reuse may be permitted for deliberate opening/closing callbacks in future styles.

MVP should avoid reuse.

---

## 46. Story Validation

Story output should verify:

* every referenced media ID exists
* media is eligible for story use
* no hard-excluded media appears
* scene IDs are unique
* story roles are valid
* at least one opening-capable scene exists
* at least one closing-capable scene exists
* no accidental duplicate media reuse occurs

---

## 47. Missing Story Categories

The engine must degrade gracefully.

If there is no airport media:

```text
do not fabricate an arrival scene
```

If there is no food media:

```text
do not require food
```

Narrative structure adapts to actual memories.

---

## 48. Small Trips

For small projects:

```text
10–20 usable media
```

the Story Engine should simplify structure.

Example:

```text
hook
exploration
highlight
closing
```

It should not create empty artificial scenes.

---

## 49. Large Trips

For large projects:

```text
hundreds or thousands of media
```

Story Engine must operate only on the candidate pool from Media Selector.

It should not receive the entire raw media library by default.

This reduces:

* context size
* cost
* latency
* narrative noise

---

## 50. Provider Independence

Story business logic should depend on an abstract text-generation provider.

Conceptually:

```text
StoryProvider
```

Possible implementations may include cloud or local LLMs.

The story schema must remain vendor-independent.

---

## 51. Local LLM Support

Local LLM support should remain possible.

The Story Engine primarily consumes text metadata rather than raw images, making local execution practical.

This provides:

* privacy
* cost control
* offline development
* provider flexibility

---

## 52. Caching

Story output may be cached based on:

```text
candidate media set
Vision/scoring state
story configuration
story prompt version
model/provider
```

Changing rendering settings should not require Story regeneration.

---

## 53. Regeneration

Users may eventually request:

```text
make it more energetic
make it more cinematic
focus more on food
use fewer selfies
```

Story regeneration should operate without repeating Media Analyzer or Vision processing where possible.

---

## 54. Story Versioning

Persist:

```text
story_version
```

and ideally:

```text
story_prompt_version
```

This allows reproducible experimentation.

---

## 55. Error Handling

Possible failures:

```text
StoryProviderUnavailable
StoryResponseValidationError
StoryInsufficientMediaError
StoryInvalidMediaReference
```

Malformed AI output must not silently proceed to rendering.

---

## 56. Testing Requirements

Automated tests should cover:

* valid structured story output
* invalid media IDs
* duplicate media references
* scene-role validation
* small-trip fallback
* missing-category fallback
* chronology handling
* candidate-pool constraint
* serialization
* provider failure

Cloud APIs should be mocked in CI.

---

## 57. Real-World Evaluation

Story quality should be evaluated using actual trips.

Questions:

```text
Does the Reel have a recognizable beginning?
Does it progress?
Are major memories represented?
Does one location dominate unnecessarily?
Does the ending feel intentional?
Does the sequence feel like a trip rather than a slideshow?
```

Human evaluation is essential.

---

## 58. Failure Modes

### Chronological Dump

Every image appears strictly by timestamp with no hierarchy.

### Highlight Dump

Only spectacular moments appear with no journey.

### AI Hallucination

Story invents locations or events.

### Scene Fragmentation

Too many tiny scenes.

### Scene Saturation

One activity dominates.

### Flat Arc

Every scene has equal importance.

### Overwriting

Too much text overlay distracts from media.

---

## 59. Quality Gates

A Story Engine implementation must not be approved if it:

1. ignores Media Selector output
2. references nonexistent media IDs
3. invents unsupported locations or events
4. produces only free-form prose
5. assigns FFmpeg operations
6. performs rendering
7. requires raw full media library by default
8. creates empty artificial scenes
9. ignores the target short-form format
10. cannot produce a coherent opening and closing strategy

---

## 60. Baseline Decision

The Story Engine is the narrative-intelligence layer of AI Travel Reel Generator.

Its contract is:

> Turn selected travel memories into a concise, structured and emotionally coherent short-form journey.

The Story Engine decides:

> What story are we telling?

The Reel Planner decides:

> Exactly how do we fit that story into 40 seconds?
