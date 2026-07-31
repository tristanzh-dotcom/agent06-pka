# Agent06 Personal Knowledge Assistant Governance

Scope: this repository.

The approved PKA specifications, current answer-destination handoff, current
shared-asset handoff, source registry, and executable tests define local
behavior.

## Knowledge and publication boundaries

- User documents, OCR output, retrieved chunks, indexes, queries, and answer
  assets are private. Keep credentials and private content out of logs,
  screenshots, URLs, fixtures, and browser output.
- Primary source evidence retains authority. Generated answers or generated
  knowledge are secondary artifacts and may not cite or reinforce themselves as
  independent evidence.
- Model output may draft analysis or wording only within a canonical registered
  route. Deterministic code owns parsing, provenance, retrieval gates, schemas,
  operation keys, destinations, and write results.
- Local save, Obsidian publication, PKA indexing, and Agent10 publication are
  different destinations. Preserve their confirmation, idempotency, partial
  failure, and recovery semantics.
- AgentAssetVault access occurs only through an approved consumer contract.
  Agent06 does not make the Vault an application or grant new consumers.

## Verification and acceptance

Select focused parser, retrieval, generator, answer-operation, destination, or
asset tests from current tests and the affected handoff. Apply compile or
JavaScript syntax checks only to changed server/UI surfaces, and exercise
Agent10 or Obsidian consumers only when their contract is directly affected.

The complete repository pytest suite is Level 4 or an approved release gate.
Completion requires source-backed evidence, schema/provenance checks for the
affected path, and explicit reporting of any external model, OCR, Obsidian, or
Agent10 integration not exercised.
