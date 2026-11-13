# Bounded IFC-Bench text path (#13)

The deterministic text path reads IFC records and never imports reference
answers. It handles authoring software/schema metadata, explicit building
identity/usage, all recorded storeys, space inventories at exact storey scope,
recorded net area quantities, door/window fire-rating availability, explicit
MEP component/system inventories, and live-load data availability.

Unsupported questions defer to the existing LLM path. Recognized questions
with missing attributes, ambiguous scope, incomplete area quantities, or
unassigned MEP system classification decline. This distinction depends on the
typed-abstention contract in #19 (PR #23); integrate that dependency before
enabling the public text path.

## Evidence and limits

Answers cite the IFC file and GlobalIds of contributing root entities.
IfcApplication/header facts cite STEP entity IDs or the header because those
records have no GlobalId. Text metadata does not receive floor-plan overlays.
Model parsing is cached by resolved path, nanosecond modification time and
size, with at most four models retained.

The implementation preserves actual source distinctions:

- Building usage is read from explicit properties, never inferred from room
  names or the filename.
- Storey counts include empty/foundation/roof records and say so. They are not
  a claim about occupied floors.
- Named space queries require an exact storey label; ordinal floor aliases
  are not guessed. Area requests require every room's explicit NetFloorArea
  or NetFootprintArea, respecting quantity/project area units. No gross-to-net
  substitution, geometry estimation, or semantic room-use grouping is added.
  Raw space records can contain overlapping gross-area zones.
- MEP classifications require explicit system assignments. Generic flow
  terminals and zero system records do not establish plumbing/heating types.
  Counts describe the supplied IFC, not the constructed building.
- Broad prose, structural judgments, inferred materials, capacity calculation,
  and compound requests outside the bounded templates remain unsupported.

## Local text grader

`stoa.text_score` post-processes JSONL from the existing evaluation runner:

```bash
.venv/bin/python -m stoa.text_score /tmp/ifc-bench-results.jsonl
```

It compares normalized exact text or explicit unavailability statements.
Punctuation/case/whitespace may vary, while signs and percent markers remain
significant. Positive and negative claims containing the same numbers are not
equivalent. Mixed references such as "unavailable, however estimated at 66 m2"
do not count as abstentions. Records explicitly marked `attempted: false` are
excluded from the score denominator.

This is a conservative **local proxy**, not semantic accuracy. Correct
paraphrases and differently formatted inventories often fail exact matching.
It intentionally leaves the shared numeric scorer and evaluation runner
unchanged while their owner has concurrent changes in flight.

## Measurements (2026-11-14 local date)

The preview contains 249 text questions across five models, with 239 distinct
question wordings. These are development observations, not held-out results.

| Measurement | Result |
|---|---:|
| Deterministic path returned source facts | 18 / 249 |
| Recognized request explicitly declined | 25 / 249 |
| Outside the bounded templates | 206 / 249 |
| Strict proxy on the 43 handled questions | 8 / 43 |
| Source-only pass over all 249 questions | 1.43 s, no API calls |
| Hitos metadata cold parse (64.1 MB) | 0.688 s |
| Hitos repeated metadata, average of 20 requests | 0.000051 s |

The reference prose sometimes includes information not established by the
supplied ARC file. For example, DigitalHub references describe thousands of
MEP components, whereas this supplied architectural IFC has zero
IfcDistributionElement records. Hitos has 69 generic flow terminals but no
explicit IfcSystem records. Neither case justifies inventing a system type.

### Bounded live baseline

Before integrating deterministic answers, the original summary-prompt LLM
was measured on a fixed five-question smoke cohort: preview IFC-Bench indices
1, 50, 128, 164 and 199 in source order (zero-based). This covers software in
four models and unavailable live-load capacity in the fifth. Prompts, model
and generation settings were unchanged; the transport disabled retries,
limited requests to five, and used a 45-second timeout per request.

| Measurement | Original LLM | Deterministic path |
|---|---:|---:|
| Normalized/abstention proxy matches | 1 / 5 | 1 / 5 |
| Hosted API calls | 5 | 0 |
| Recorded token usage | 27,254 | 0 |
| Provider-reported cost | $0.00413675 | $0 |

All five baseline requests succeeded in 43.2 seconds including summary
construction. The previous number-overlap scorer reported 2/5; that score is
not comparable to this text proxy. The unchanged strict score does not imply
that the four source-derived software answers are factually wrong: the proxy
rejects their different formatting and extra source fields. It also does not
establish semantic correctness across the full benchmark. No 249-request live
evaluation was performed.

### Integration validation

The existing router and Answer contract from the pending #19 branch were
copied into a temporary source tree, alongside this implementation. Router
tests verify that absent usage cannot reach an LLM and unsupported templates
still can. The rest of the repository was left unchanged.

The complete test suite passes against that combined interface. `make check`
also passes: Swiss 99.2% on 2,358 questions and IFC models 97.6% on 1,049,
unchanged from #12. Public integration must be revalidated on main after #19
lands; these are dependency-integration results, not a claim that #19 is
already merged.
