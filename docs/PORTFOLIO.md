# Portfolio Case

Live demo: https://steelai-workbench.streamlit.app/

Source: https://github.com/shidao23/steelai-workbench

## Problem

Wear-resistant-steel research data were distributed across tables, empirical equations, microscopy outputs and scripts. The challenge was to create a useful AI-assisted workflow without allowing a language model to replace scientific calculation or overstate weak evidence.

## Solution

- Built a six-area Streamlit research workbench.
- Defined a versioned composition-process-microstructure-property-physics data contract.
- Wrapped empirical physics in tested functions with applicability warnings.
- Integrated MTEX/EBSD and micro-SAM through isolated specialist adapters.
- Added a read-only Research Agent with tool and privacy limits.
- Added deterministic evidence levels, claim gates and reproducible run manifests.

## Verified engineering results

- 54 offline tests passing.
- 25-case Agent evaluation contract.
- CI-safe synthetic fixtures.
- append-only data intake with duplicate and scope blocking.
- six consolidated navigation areas.
- public/private data boundary enforced by repository design.

## Scientific result boundary

The portfolio demonstrates research-software engineering and evidence-aware AI application. It does not publish or claim experimental conclusions from private steel data.

## Interview demo

1. Show the synthetic B/R comparison.
2. Run the Physics Engine and inspect warnings.
3. Open the data-contract readiness panel.
4. Explain field/specimen hierarchy and pseudoreplication prevention.
5. Show Agent evaluation and the reproducible Research Case manifest.
