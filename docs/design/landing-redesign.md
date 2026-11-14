# Landing redesign: source-specific motion scenarios

## Decision (2026-11-14)

Keep `Hero.tsx` and `EvidenceDemo.tsx` unchanged. The hero already animates a verified Swiss Dwellings floor-plan question through typed input, source routing, SVG camera movement, polygon evidence, answer display, and a declined answer. `web/src/data/evidence.ts` holds the actual source geometry and fixture values.

## This branch

- Adds `ScenarioShowcase.tsx` after the problem statement, before source lanes.
- Adds three selectable motion demonstrations: IFC, raster image, and PDF text.
- Mirrors the hero's staged cadence but **does not claim those examples are actual inference results**.
- Uses simple source-relevant SVG diagrams and existing site tokens, with no new animation dependency.
- Changes the primary navigation to point to Scenarios and updates the problem statement and run section to emphasize verification.
- Leaves the verified Swiss hero and existing dataset/evaluation logic untouched.

## Source types and honest output states

| Scenario | What the motion illustrates | What can be asserted |
| --- | --- | --- |
| IFC | Element selection with source identity | The deterministic IFC path can cite GlobalIds. This animation is illustrative and does not assess load capacity. |
| PNG | Candidate window regions, numbered and reviewed | Unseen PNG detections remain unreviewed until an operator inspects the entire image. No perception benchmark result is claimed. |
| PDF | Matching text and source region highlight | This is an interface illustration, not a claim of an actual sheet answer. |

## Source-of-truth materials

- `docs/unseen-png.md` states that unseen PNG boxes are proposals and that no independent unseen evaluation cohort has yet been supplied.
- `docs/research/ifc-bench-text.md` states deterministic IFC coverage and boundaries.
- `docs/adr/0003-swiss-lane-uses-rules-not-an-llm.md` explains the supported Swiss geometry route.
- `src/stoa/eval/baseline.json` stores regression gates, not generalization scores.

## Next work after review

1. Replace illustrative IFC / PNG / PDF scene geometry with approved exported sample artifacts and measured evidence, **only when verified**.
2. Add a source-selection action from each scene to the running viewer, behind a real configured demo URL; don't invent a broken CTA.
3. Validate at widths 320, 390, 768, 1024 and 1440px, with keyboard-only interaction, reduced motion and slow network throttling.
4. Run `cd web && pnpm install && pnpm build && pnpm lint`; check CSS contrast and screenshot the hero and each scene.
5. Preserve pause / replay controls and keep animations short and composited. W3C WCAG 2.2 SC 2.2.2 applies to extended auto-updating/moving media.

## Non-goals

- Changing the verified Swiss hero motion.
- Claiming PNG detection accuracy, inferred load-bearing structure, georeferencing, or fabricated PDF measurements.
- Introducing a large animation framework or decorative motion without evidentiary meaning.
