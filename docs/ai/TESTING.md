# Testing Guide

## Philosophy
Run the smallest relevant checks first.
Expand only when the patch or risk justifies it.

## Testing layers in this repo

### Layer 1 — contract/artifact tests
Purpose:
- verify UAFX -> bridge -> MOCK handoff structure

Examples:
- bridge export shape
- candidate.json generation
- witness_plan.json generation
- mock_seed.json generation
- importer artifact correctness

### Layer 2 — dry-run / tooling tests
Purpose:
- verify seeded workflow inputs are sane

Examples:
- dry-run summary
- seed workdir generation
- relation file generation
- bias config generation
- corpus histogram summaries

### Layer 3 — runtime smoke tests
Purpose:
- verify seeded fuzzing starts and loads the expected inputs

Examples:
- seeded short run
- unseeded short baseline
- config/debug summaries
- run-limited smoke tests

### Layer 4 — comparative experiments
Purpose:
- measure whether seeded structure actually helps

Examples:
- seeded vs unseeded corpus KVM ratio
- syscall family histogram deltas
- coverage or corpus growth comparisons
- crash or warning comparisons

## Default verification order
1. nearby unit tests
2. artifact generation tests
3. importer / tooling tests
4. dry-run checks
5. short seeded smoke run
6. seeded vs unseeded comparison only when ready

## Required in summaries
Every implementation summary must include:
- commands run
- whether they passed or failed
- whether verification was artifact-level, dry-run, or runtime-level
- any known untested paths

## Examples
### Bridge mapping change
- run bridge tests
- regenerate demo seed
- inspect `mock_seed.json`

### MOCK importer change
- run importer tests
- run seed prep script
- inspect generated workdir

### Healer CLI/debug change
- run targeted tests
- run dry-run command
- optionally run a short `--max-seconds` smoke run

### Bias logic change
- run importer tests
- inspect bias artifact
- compare seeded vs unseeded histograms if feasible