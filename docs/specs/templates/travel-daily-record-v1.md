# Travel Daily Record v1

## Reference observations

This design grammar is inspired by engineering analysis of a short user-provided travel-diary reference video. Observed qualities include bright whitespace, alternating fullscreen and collage composition, grids and layered photo cards, diary-like typography, generic decorative marks, restrained push/pan/translate motion, rapid photo replacement, foreground/background depth, and beat-aware changes.

The reference video itself is not embedded or committed. No proprietary CapCut data, fonts, stickers, music, source files, or exact timeline is a dependency.

## Our implementation contract

`travel_daily_record_v1` is an adaptive `travel_diary` template. It has no fixed duration or media count. Hook prefers hero/fullscreen/title treatments with limited complexity. Exploration prefers two-up, three-up, grid, and collage. Experience permits layered cards, collage, fullscreen, and beat montage. Highlight increases hero/fullscreen/montage emphasis. Closing prefers layered cards, a closing card, or a hero image with reduced density.

Preferences are deterministic, not rigid. Consecutive event identity encourages coherent grouping. Complex blocks avoid immediate repetition and are bounded by a maximum consecutive count. Title cards are rare; closing cards are closing-only. Existing global music anchors influence boundary metadata without re-analysis. No-music mode follows the same stable sequence without beat metadata.

All geometry uses normalized coordinates. Typography and decorations reference abstract style tokens only. Motion and transitions are semantic future-renderer intents.
