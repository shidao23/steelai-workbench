# Model Card

## Deterministic layer

The Physics Engine exposes empirical estimates such as Ms, Ac1, Ac3, Tnr, Ceq and Pcm. Every result is treated as a model estimate with input checks and warnings. It is not an experimental measurement and it is not a fracture-toughness predictor.

## Language-model layer

The optional Research Agent is a bounded evidence-synthesis layer. It can call only whitelisted read-only tools and cannot modify source data, launch specialist jobs or execute arbitrary code. The public edition disables external AI by default.

## Evaluation

A fixed 25-case benchmark evaluates data grounding, physics interpretation, SEM/EBSD boundaries, privacy and permissions using deterministic scoring. Evaluation artifacts are designed to omit prompts, answers, tool arguments and local paths.

## Specialist adapters

MTEX and micro-SAM run in separate local environments. This repository contains orchestration contracts but no MATLAB installation, model weights, raw images or proprietary databases.

## Limitations

- empirical equations require literature and range review;
- no experimental calibration is included in the public edition;
- one image field is not an independent specimen;
- model output cannot establish causality;
- current data are insufficient for reliable supervised machine learning.
