# Review Rubric

## Check 1: correctness
- Does the implementation do what the plan says?
- Are edge cases handled?
- Are unsupported cases explicit and typed (not silently papered over)?
- Are failures reported honestly?

## Check 2: architecture
- Does the patch preserve the UAFX -> bridge -> runtime-backend separation?
- Did the bridge absorb too much semantics?
- Did any stage become too dependent on raw static-analysis assumptions?
- Was a smaller patch possible?

## Check 3: target-pack discipline
- Is pack selection deterministic and driven by artifacts (not environment)?
- Are pack-specific assumptions clearly documented as grounded vs heuristic?
- Does KVM remain intact as a legacy/initial pack (non-regression)?

## Check 4: testing
- Were the right tests added or updated?
- Are artifact-level tests and runtime-level tests distinguished clearly?
- Is verification strong enough for the changed pack(s) and family(ies)?

## Check 5: scope discipline
- Did the patch touch unrelated files?
- Did it introduce hidden follow-up work?
- Did it silently change interfaces or workflows?

## Output format

### Findings
- severity: high/medium/low
- file
- issue
- suggested fix

### Decision
- approve
- approve with follow-ups
- request changes
