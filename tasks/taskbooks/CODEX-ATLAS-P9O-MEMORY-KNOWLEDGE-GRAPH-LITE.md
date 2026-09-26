# CODEX-ATLAS-P9O-MEMORY-KNOWLEDGE-GRAPH-LITE

## Goal

Build a lightweight knowledge relationship layer on top of existing MemoryOS without replacing existing facts, approvals, identity, or commitment systems.

## Scope

Implement:

- deterministic knowledge nodes
- deterministic knowledge relationships
- evidence-backed edges
- graph traversal helpers for relevant user knowledge
- integration hooks for future planning and autonomous tasks

## Do Not Change

- Do not bypass candidate approval
- Do not auto-promote rejected memories
- Do not modify identity safety rules
- Do not modify commitment lifecycle rules
- Do not store credentials
- Do not replace existing SQLite memory contracts

## Acceptance

Must provide:

- executable tests with measured results
- source/evidence preservation
- deterministic graph generation
- backward compatibility with existing memory APIs

## KNOWN-BASELINE

Read docs/KNOWN-BASELINE-ISSUES-2026-09-26.md before execution.

## Deliverable

Create result file:

tasks/results/CODEX-ATLAS-P9O-MEMORY-KNOWLEDGE-GRAPH-LITE.result.md

Stop after completion.
