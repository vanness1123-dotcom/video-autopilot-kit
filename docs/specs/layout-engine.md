# Static Layout Engine

## Responsibility

Sprint 11.2a resolves where existing Visual Plan media layers appear. It consumes a semantic Visual Plan and persisted media dimensions, then embeds one renderer-independent `resolved_layout` in every Visual Block. It never changes shot grouping, ownership, order, event identity, story phase, or Reel Plan timing, and it performs no rendering, animation, Vision, or music analysis.

The explicit pipeline stage is `layout-plan`, after `template-plan` and before future Motion, Overlay, and Renderer integration.

## Contract

Each `visual_plan.blocks[].resolved_layout` contains:

```json
{
  "version": "1.0",
  "strategy": "two_up_vertical.v1",
  "coordinate_space": "normalized",
  "safe_area": {"x": 0.04, "y": 0.04, "width": 0.92, "height": 0.92},
  "safe_area_policy": "inside",
  "background": {"type": "solid", "token": "canvas_light"},
  "overlap_policy": "prohibited",
  "slots": []
}
```

Each slot contains deterministic `slot_id`, `shot_id`, `media_id`, normalized `x`, `y`, `width`, `height`, integer `z_index`, `fit_mode` (`cover` or `contain`), static `rotation_deg`, static `opacity`, and an abstract rectangular or rounded-rectangle clipping intent.

## Strategies

The initial strategies cover fullscreen, inset hero, vertical/horizontal two-up, hero-plus-pair three-up, bounded two/three/four-cell grids, overlapping collage, layered-card hierarchy, full-canvas beat-montage replacement, title shell, and closing shell. Persisted width and height select the horizontal two-up strategy only for two landscape items; portrait, square, mixed, and unknown pairs use the conservative vertical strategy.

Structured two-up, three-up, and grid layouts prohibit overlap. Collage and layered-card layouts require deterministic intentional overlap. Beat montage uses temporal-replacement overlap without defining animation; existing Visual Plan timing remains authoritative.

## Invalidation

Layout resolution replaces only `visual_plan` with its additive resolved layouts and removes stale `render` state when the plan changes. Analyzer data, Vision, Scores, Events, Creative Direction, Selection, Story, Music state, Reel Plan, and Template Definition remain unchanged.

Renderer does not consume this contract until the later Renderer Integration sprint.

## Sprint 11.2b deterministic strategy families

Multi-shot blocks resolve from a bounded set of compatible candidates. Candidate scoring favors structural compatibility with the persisted orientation signature and Story phase, then applies an eight-point penalty when the same strategy appeared in either of the two preceding blocks and a comparable alternative exists. Repetition never makes an orientation-incompatible or materially inferior candidate win. A SHA-256 digest of block type, phase, strategy, ordered shot IDs, and ordered event IDs is used only to break equal-score ties; no runtime randomness is used.

Two-up supports vertical, horizontal, and left/right asymmetric families. Three-up supports equal portrait cards, hero-plus-pair, landscape stack, and a landscape-dominant mixed family. Grid retains bounded two/three/four-cell forms with limited dominant-cell alternatives. Collage supports staggered, dominant, asymmetric, and fan compositions. Layered cards remain distinct: the first owned shot is the explicit primary foreground card at the highest unique z-index, while supporting cards sit behind it with deliberate whitespace.

Each resolved layout persists compact `selection_reasons` including orientation signature, semantic compatibility, any repetition decision, and final selection score, plus `candidate_count`. Landscape media placed into structurally narrow cards uses `contain`; aspect-compatible slots generally use `cover`. No focal point is invented.

All Sprint 11.2a bounds, ownership, safe-area, overlap, and timing validation remains active. Validation additionally rejects known strategies that are incompatible with the block's media count/orientation and requires unique z-order for overlapping cards.
