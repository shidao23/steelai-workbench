# Data Card: SteelAI Public Demo

## Scope

The tracked B-DQ and R-DQ tables are deliberately synthetic fixtures for application testing and portfolio demonstration. They are not transformed, anonymized or rounded versions of confidential experimental records.

## Tables

- `samples.csv`: two synthetic research conditions.
- `composition.csv`: plausible but artificial steel compositions.
- `process.csv`: partial synthetic direct-quench routes.
- `microstructure.csv`: blank measurement fields with explicit demo notes.
- `properties.csv`: artificial mechanical-property summaries.
- `evidence_index.csv`: header only; no file paths.

## Intended use

- UI demonstration
- deterministic unit and integration tests
- data-contract validation
- empirical-physics workflow testing
- evidence and Agent guardrail evaluation

## Prohibited interpretation

The values must not be cited as measured properties, used for alloy-design decisions, or interpreted as evidence about a real B/R material pair.

## Missingness and independence

Blank is missing, not zero. The `replicates` field is a synthetic summary and does not establish independent specimens. No inferential statistics or causal claims are supported.
