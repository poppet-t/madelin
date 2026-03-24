# Review Rubric

## Check 1: correctness
- Does the implementation do what the plan says?
- Are edge cases handled?
- Are seeded/unseeded paths both considered where relevant?
- Are failures reported honestly?

## Check 2: architecture
- Does the patch preserve the UAFX -> bridge -> MOCK separation?
- Did the bridge absorb too much semantics?
- Did MOCK become too dependent on raw static-analysis assumptions?
- Was a smaller patch possible?

## Check 3: KVM realism
- Does the patch preserve or improve the KVM setup/resource chain?
- Are KVM-specific assumptions clearly marked as grounded vs heuristic?
- Does this likely improve KVM focus, or only artifact appearance?

## Check 4: testing
- Were the right tests added or updated?
- Are artifact-level tests and runtime-level tests distinguished clearly?
- Is verification strong enough for the changed behavior?

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