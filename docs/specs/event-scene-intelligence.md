# Event and Scene Intelligence Specification

**Version:** 1.0
**Stage:** Sprint 7.5

The Event stage sits after scoring/Vision understanding and before selection. It deterministically groups every source media item into a coherent travel experience without network inference, embeddings, fabricated timestamps, or GPS.

## Manifest contract

`events.version` is `1.0`. Each item contains a stable ordinal `event_id`, conservative `label`, ordered original `media_ids`, dominant category, scene/activity summaries, photo/video counts, explainable evidence, and a deterministic `evidence_score` (not statistical confidence). Each media object gains `event.event_id`, `event.ordinal`, and a lightweight `event.scene_role`.

## Evidence and boundaries

Semantic evidence combines category, activity, compatible scene, landmark equality, people state, and tag/object/description token overlap. Capture-time or filename-number proximity supports a merge only when semantic similarity also passes the configured threshold. Strong distinctive overlap can connect unsequenced media. Large time/sequence gaps and incompatible semantic context preserve boundaries. Folder names alone never establish an Event.

## Ordering and downstream ownership

Events use reliable capture chronology, then numeric filename sequence, source-manifest order, and ID tie-breaking. Within an Event the controlled roles are establishing, people, activity, detail, motion, highlight, and closing; missing roles are not synthesized. Story permits one explicitly marked hook teaser and otherwise emits contiguous Event blocks. Planner reduction keeps Event representatives and reports event switches and fragmentation.

Running `events` preserves analyzer inventory, Vision, and scoring. It removes selection, Story, Reel Plan, render state, and media-level selection because all depend on the prior grouping.
