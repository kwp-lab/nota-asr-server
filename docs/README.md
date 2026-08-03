# Nota ASR Server Engineering Guide

This directory is the durable engineering context for people and AI agents.
Read the documents in this order:

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

When behavior changes, update code, tests, and the corresponding document in
the same change.
