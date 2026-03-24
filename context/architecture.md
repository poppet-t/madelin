# Architecture

## Pipeline
The system is organized as a staged pipeline:

`warning -> candidate extraction -> mapping/classification -> SMT encoding/solve -> witness plan -> runtime emission -> MOCK import/seeded fuzzing`

## Main stages

### 1. Extraction / normalization
Transforms raw static-warning material into a canonical `candidate.json`.

Responsibilities:
- normalize warning structure
- preserve provenance
- recover relevant contexts
- attach cross-entry metadata
- keep output stable and machine-readable

### 2. Mapping / entry classification
Maps candidate contexts into supported entry classes and syscall-template fragments.

Responsibilities:
- identify supported entry families
- classify entry kinds such as ioctl/read/write/sysfs
- attach manual or template-assisted mappings
- stay conservative when evidence is weak

### 3. SMT stage
Encodes structural feasibility constraints into stock Z3 and extracts a witness plan.

Responsibilities:
- encode ordering requirements
- represent partial-order constraints
- model basic resource and alias relationships
- produce SAT/UNSAT outcomes with useful witness metadata

### 4. Runtime emission
Converts candidate + witness plan into a deterministic pseudo-syzkaller scaffold or MOCK-facing seed material.

Responsibilities:
- preserve plan ordering
- emit stable prefixes
- keep dynamic repair in the runtime/fuzzing stage, not the bridge stages
- expose relations/hints to downstream tooling

### 5. MOCK handoff
Imports bridge outputs into MOCK seed and bias formats for targeted fuzzing.

Responsibilities:
- preserve stable resource prefixes
- preserve intended ordering edges
- make bridge intent visible downstream
- fail clearly when the imported seed is structurally unsupported

## Design invariants
- Bridge stages should be deterministic given the same inputs.
- Dynamic fuzzing is where argument/value healing can occur.
- Artifact boundaries matter more than local convenience.
- Narrow support is preferable to fake generality.
