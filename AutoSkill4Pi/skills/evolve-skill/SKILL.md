---
name: evolving-skills
description: Use when a skill has been used multiple times but still gets corrections, or when you notice a skill's guidance is incomplete or outdated
version: 0.1.0
triggers: [skill gets corrections, skill used many times, skill guidance incomplete, skill outdated]
tags: [skill evolution, quality improvement, darwin evaluation, skill maintenance]
---

# Evolving Skills

## Overview

Skills degrade over time as contexts change or edge cases emerge. Evolution is the process of evaluating and improving existing skills using a 9-dimension rubric.

**Core principle:** A skill that keeps generating corrections is a skill that needs evolution.

## When to Evolve

**Evolve when:**
- A skill has been used 3+ times but user still corrects the approach
- You read a skill and notice gaps in constraints or workflow
- A skill's triggers no longer match real usage patterns
- External tools/APIs the skill references have changed

**Don't evolve for:**
- Minor typos or formatting (just fix inline, no version bump needed)
- First-time corrections (update the skill, but full evolution isn't needed yet)

## 9-Dimension Evaluation (Darwin Rubric)

Read the skill, then evaluate each dimension:

| # | Dimension | Question to Ask |
|---|-----------|-----------------|
| 1 | **Goal clarity** | Is the goal statement specific and actionable? |
| 2 | **Constraint completeness** | Are all must-do/must-not-do rules captured? |
| 3 | **Workflow reasonability** | Do the steps follow a logical order? Any missing steps? |
| 4 | **Reusability** | Can this skill apply across projects, or is it too specific? |
| 5 | **De-identification** | Is the skill free of personal/sensitive information? |
| 6 | **Trigger accuracy** | Do triggers match real situations where this skill applies? |
| 7 | **Tag coverage** | Are tags comprehensive enough for discovery? |
| 8 | **Prompt executability** | Can an agent follow this without ambiguity? |
| 9 | **Anti-pattern check** | Does the skill avoid known anti-patterns (vague descriptions, narrative style)? |

## Evolution Workflow

1. **Read** the current SKILL.md
2. **Evaluate** each of the 9 dimensions (score: pass/fail/needs-improvement)
3. **Identify** the top 2-3 dimensions that need improvement
4. **Rewrite** the SKILL.md addressing those dimensions
5. **Bump version** (0.1.0 → 0.1.1 for fixes, 0.1.0 → 0.2.0 for significant changes)
6. **Verify**: would the recent corrections be handled by the updated skill?

## Version Bumping

- **Patch** (0.1.0 → 0.1.1): fix typos, add missing constraints, clarify wording
- **Minor** (0.1.0 → 0.2.0): restructure workflow, add new sections, change triggers
- **Major** (1.0.0 → 2.0.0): fundamental rewrite (rare)

## Common Evolution Patterns

| Symptom | Likely dimension | Fix |
|---------|-----------------|-----|
| Agent skips the skill | Trigger accuracy (#6) | Rewrite triggers to match real situations |
| Agent follows skill but gets wrong result | Constraint completeness (#2) | Add missing must-do/must-not-do rules |
| Agent misinterprets instructions | Prompt executability (#8) | Remove ambiguity, add concrete examples |
| Skill never gets loaded | Tag coverage (#7) | Add more keywords agents would search for |

## Anti-Patterns to Avoid During Evolution

- Adding content for hypothetical scenarios (stick to observed failures)
- Making the skill longer without adding clarity (prefer concise over verbose)
- Removing constraints that "seem obvious" (if they were needed once, keep them)
