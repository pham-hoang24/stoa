# Application drawings and benchmark cases have separate boundaries

The user changed the milestone to answering questions about unseen uploaded PNGs. Application inference now accepts validated drawing pixels and an explicit count task; reference answers, source-folder identities, and dataset-derived priors belong outside that boundary. This supersedes ADR-0001's source-name routing for application uploads: image contents determine the capability, while existing benchmark adapters remain compatible during migration.

Evaluation annotations stay in a separate workflow, grouped by project/design and checked for duplicate pixel content. Model proposals and user corrections remain distinguishable; corrected model output is not silently promoted to independent held-out ground truth. Image coordinates are source pixels, and proposed counts remain visibly unreviewed until a user inspects the complete drawing.
