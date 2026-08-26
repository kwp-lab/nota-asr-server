# Nota ASR Server Engineering Guide

This directory is the durable engineering context for people and AI agents.
Read the documents in this order:

Contributors should first read the repository-level
[`CONTRIBUTING.md`](../CONTRIBUTING.md) for workflow, privacy, and compatibility
rules, then use this index to find the specification that owns a change.

1. [`business-context.md`](business-context.md): product goals and scope boundaries.
2. [`api-contract.md`](api-contract.md): the client-facing contract that must remain stable.
3. [`architecture.md`](architecture.md): runtime components and request flow.
4. [`model-strategy.md`](model-strategy.md): SenseVoice, Paraformer, VAD, and CAM++ choices.
5. [`development.md`](development.md): local setup, tests, and contribution workflow.
6. [`operations.md`](operations.md): deployment, health checks, logs, and recovery.
7. [`security.md`](security.md): trust boundary and production hardening.
8. [`decisions/`](decisions): architectural decision records.
9. [`speaker-embeddings.md`](speaker-embeddings.md): stateless CAM++ extraction
   for client-local speaker identification.
10. [`decisions/0008-clean-speaker-sample-analysis.md`](decisions/0008-clean-speaker-sample-analysis.md):
    why enrollment purity is analyzed independently from transcription output.
11. [`decisions/0009-paraformer-punctuation-speaker-segmentation.md`](decisions/0009-paraformer-punctuation-speaker-segmentation.md):
    why Paraformer maps CAM++ speakers to CT-Punc sentence boundaries.
12. [`decisions/0010-turn-aligned-speaker-segmentation.md`](decisions/0010-turn-aligned-speaker-segmentation.md):
    how SenseVoice and Fun-ASR-Nano recover stable speaker turns inside one VAD
    segment without changing the public API.
13. [`decisions/0011-separate-local-and-meeting-speaker-clustering.md`](decisions/0011-separate-local-and-meeting-speaker-clustering.md):
    why dense window embeddings and sparse whole-meeting centroids use separate
    deterministic clustering strategies.
14. [`open-source-compliance.md`](open-source-compliance.md): dependency license
    policy, generated notices, SBOM boundaries, and model-license separation.
15. [`decisions/0012-locked-open-source-compliance.md`](decisions/0012-locked-open-source-compliance.md):
    why the CPU container uses a frozen extra and keeps Python, OCI, and model
    license inventories separate.
16. [`decisions/0013-standalone-windows-runtime-and-manager.md`](decisions/0013-standalone-windows-runtime-and-manager.md):
    ownership and lifecycle boundaries for the portable CPU Runtime, native
    Manager, external model data, and the original installation proposal.
17. [`decisions/0014-portable-zip-windows-distribution.md`](decisions/0014-portable-zip-windows-distribution.md):
    why the official Windows package is an owner-built portable ZIP and how
    Manager distinguishes portable from future installed configuration.
18. [`decisions/0015-model-hotword-capabilities-and-batch-request.md`](decisions/0015-model-hotword-capabilities-and-batch-request.md):
    why hotword support is model-scoped and persisted with durable jobs.
19. [`decisions/0016-generate-sboms-at-distribution-boundaries.md`](decisions/0016-generate-sboms-at-distribution-boundaries.md):
    why Linux, Docker, and Windows SBOMs are generated from their actual build
    environments instead of committing one platform-specific root file.

When behavior changes, update code, tests, and the corresponding document in
the same change.
