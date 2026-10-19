---
name: evolving-skills
description: Use when a skill has been used multiple times but still gets corrections, when you notice a skill's guidance is incomplete or outdated, or when optimizing skill quality
version: 0.2.0
triggers: [skill gets corrections, skill used many times, skill guidance incomplete, optimize skill, skill quality check, skill evaluation, darwin]
tags: [skill evolution, quality improvement, darwin evaluation, skill maintenance, auto optimize]
---

# Evolving Skills

## Overview

Skills degrade over time as contexts change or edge cases emerge. Evolution is the process of evaluating and improving existing skills using a 9-dimension rubric.

**Core principle:** A skill that keeps generating corrections is a skill that needs evolution. Evaluate structure + effectiveness, improve iteratively, keep only what measurably helps.

## When to Evolve

**Evolve when:**
- A skill has been used 3+ times but user still corrects the approach
- You read a skill and notice gaps in constraints or workflow
- A skill's triggers no longer match real usage patterns
- External tools/APIs the skill references have changed
- User explicitly asks to optimize or evaluate a skill

**Don't evolve for:**
- Minor typos or formatting (just fix inline, no version bump needed)
- First-time corrections (update the skill, but full evolution isn't needed yet)

## 9-Dimension Evaluation Rubric (Total 100 points)

> Based on SkillLens (arXiv 2605.23899): LLM-as-judge accuracy is only 46.4% without meta-skill dimensions, improves to 73.8% with them. This rubric strengthens dim3/dim5 and adds dim9 to reduce optimistic bias.

### Structure Dimensions (59 points) — Static Analysis

| # | Dimension | Weight | Scoring Criteria |
|---|-----------|--------|------------------|
| 1 | **Frontmatter quality** | 7 | name规范、description包含做什么+何时用+触发词、≤1024字符、**禁止结尾加"灵活应用/根据情况判断"等空话** |
| 2 | **Workflow clarity** | 12 | Steps are clear, executable, numbered, each with explicit input/output |
| 3 | **Failure mode encoding** | 12 | **Must explicitly encode failure modes** (write "if X fails → Y" branches); has fallback paths, error recovery; **only writing positive flow without failure branches loses ≥3 points** |
| 4 | **Checkpoint design** | 6 | Critical decisions have confirmation points; **checkpoints must be visually marked (🔴/STOP/CHECKPOINT), just "if...suggest..." wording doesn't count** |
| 5 | **Executable specificity** | 18 | Not vague, has specific parameters/formats/examples, directly executable; **prohibit "suggest/could consider/depending on situation/flexible" softening wording — ≥3 occurrences loses ≥3 points** |
| 6 | **Resource integration** | 4 | references/scripts/assets cited correctly, paths reachable |

### Effectiveness Dimensions (35 points) — Requires Testing

| # | Dimension | Weight | Scoring Criteria |
|---|-----------|--------|------------------|
| 7 | **Overall architecture** | 12 | Structure is clear, not redundant or missing; **redundant/AI-sounding filler paragraphs lose 1 point each** |
| 8 | **Test performance** | 23 | Run 2-3 test prompts, does output quality match skill's claimed capabilities? |

### Meta-skill Dimension (6 points) — Anti-patterns & Blacklist

| # | Dimension | Weight | Scoring Criteria |
|---|-----------|--------|------------------|
| 9 | **Anti-patterns & blacklist** | 6 | **Skill must have "don't do" counter-examples**; only writing "should do X" without "don't do Y" loses ≥3 points; red lights/dangerous actions/anti-patterns should be in separate section |

### Scoring Rules
- Dimensions 1-7, 9: Score 1-10 each, multiply by weight to get dimension score
- Dimension 8 (test performance): Run 2-3 test prompts, score 1-10 based on output quality
- **Total score = Σ(dimension score × weight) / 10**, max 100
- ⚠️ **Absolute total score is for triage only (ranking "which is weakest, fix first"), never for keep/revert decisions.** LLM judge scores can swing ±8 on the same text. For keep/revert, use before/after comparison.

### About "Test Performance" Dimension

This is the biggest difference from pure structural scoring. Scoring method:

1. Design 2-3 **typical user prompts** for each skill (not edge cases, most common use scenarios)
2. Execute: one run with skill, one without skill (baseline)
3. Compare output quality, score from these angles:
   - Did output fulfill user intent?
   - Compared to baseline without skill, is quality improvement obvious?
   - Any negative effects introduced by skill (over-redundancy, going off-track, weird formatting)?

If subagent execution is unavailable (timeout/resource limits), degrade to "dry run verification": after reading skill, simulate execution of a typical prompt, judge if flow is reasonable; must mark `dry_run` in results log. **Dry run ratio > 30% → evaluation invalidation warning** (dim8 effectiveness dimension weight 23%, without full_test verification scores are unreliable).

---

## Autonomous Optimization Loop

### Phase 0: Initialization

```
1. Confirm optimization scope:
   - All skills → scan ~/.pi/agent/skills/*/SKILL.md
   - Specific skills → user-specified list
2. Initialize results log (if doesn't exist)
3. Read existing results log to understand optimization history
```

### Phase 0.5: Test Prompt Design

Before evaluation, design test prompts for each skill. This step is critical — without test prompts, "test performance" dimension can't be scored.

```
for each skill:
  1. Read SKILL.md, understand what it does
  2. Design 2-3 test prompts, covering:
     - Most typical use scenario (happy path)
     - One slightly complex or ambiguous scenario
  3. Save to skill directory/test-prompts.json:
     [
       {"id": 1, "prompt": "What user would say", "expected": "Brief description of expected output"},
       {"id": 2, "prompt": "...", "expected": "..."}
     ]
```

### Phase 1: Baseline Evaluation — For Triage

> **Absolute scores in this phase are for triage ranking (deciding what to fix first), not keep/revert baseline.**

```
for each skill in optimization scope:

  # Structural scoring (main agent can do)
  1. Read SKILL.md full text
  2. Score dimensions 1-7 item by item (with brief reasoning)

  # Effectiveness scoring (use subagent if available, independent from main agent)
  3. For each test prompt, spawn subagent if possible:
     - with_skill: execute test prompt with SKILL.md
     - baseline: execute same prompt without skill
  4. Compare two outputs, score dimension 8

  # Summarize
  5. Calculate weighted total score
  6. Record to results log
```

**If subagent unavailable** (timeout, environment limits), score dimension 8 with dry run verification, mark `dry_run`. Don't skip this dimension just because tests can't run — even simulated reasoning is better than completely ignoring effectiveness.

After baseline evaluation, display scorecard:

```
┌──────────────────────────┬───────┬──────────────┬──────────────┐
│ Skill                    │ Score │ Structure Gap │ Effectiveness Gap │
├──────────────────────────┼───────┼──────────────┼──────────────┤
│ code-review-checklist    │ 78    │ Boundary conditions │ Test prompt 2 │
│ formal-report-style      │ 72    │ Instruction specificity │ Baseline flat │
├──────────────────────────┼───────┼──────────────┼──────────────┤
│ Average                  │ 75    │              │              │
└──────────────────────────┴───────┴──────────────┴──────────────┘
```

### Phase 2: Optimization Loop

After baseline, sort by score low-to-high, optimize weakest first.

```
for each skill:
  round = 0
  while round < MAX_ROUNDS (default 3):
    round += 1

    # Step 1: Diagnose
    Find dimension with largest weighted gap: weighted_gap = weight × (10 - score) / 10
    # Why not "lowest raw score": low-weight dimensions create illusion of progress
    
    # Step 2: Propose improvement
    For that dimension, generate 1 specific improvement plan:
      - What to change (specific section/line)
      - Why change (which rubric item it addresses)
      - Expected score improvement

    # Step 3: Execute improvement
    Edit SKILL.md

    # Step 4: Before/after comparison
    Read both versions:
      - Before: original SKILL.md (can use git if available, or backup copy)
      - After: current SKILL.md
    Compare against 9-dimension rubric as **comparison criteria** (not absolute scores), return {better | worse | tie} + reasoning

    # Step 5: Decision
    if after >= before:  # majority says after ≥ before (including tie)
      status = "keep"
      # Auto-break if consecutive 2 rounds show minimal improvement (Δ < 2 points)
    else:                # majority says worse — this is real regression
      status = "revert"
      Restore before version
      Record to results log
      break

    # Step 6: Log
    Append to results log

  # After each skill optimization, show change summary:
  #   - What changed (before vs after)
  #   - Score changes (which dimensions improved/declined)
  #   - Test prompt output comparison (if tested)
```

### Phase 2.5: Exploratory Rewrite (Triggered on Demand)

When hill-climbing breaks in round 1 for 2 consecutive skills (can't improve), propose an "exploratory rewrite":

```
1. Select a bottleneck skill
2. Save current best version
3. Rewrite SKILL.md from scratch (not fine-tuning, reorganize structure and expression)
4. Re-evaluate
5. if rewrite > saved: adopt rewrite
   else: restore saved version
```

This solves hill-climbing's local optimum problem — sometimes you need to "tear down then rebuild" to break through bottlenecks.

### Phase 3: Summary Report

```
## Optimization Report

### Overview
- Skills optimized: N
- Total experiments: M
- Improvements kept: X (Y%)
- Reverts: Z
- Test verification: A full tests / B dry runs

### Score Changes
┌──────────────────────────┬────────┬────────┬────────┐
│ Skill                    │ Before │ After  │ Δ      │
├──────────────────────────┼────────┼────────┼────────┤
│ code-review-checklist    │ 78     │ 87     │ +9     │
│ formal-report-style      │ 72     │ 83     │ +11    │
├──────────────────────────┼────────┼────────┼────────┤
│ Average                  │ 75     │ 85     │ +10    │
└──────────────────────────┴────────┴────────┴────────┘

### Main Improvements
1. [skill-A] Added boundary condition handling, test output quality improved significantly
2. [skill-B] Reorganized workflow structure, baseline comparison advantage increased
```

---

## Results Log Format

```
timestamp	skill	old_score	new_score	status	dimension	note	eval_mode
2026-10-19T10:00	code-review-checklist	-	78	baseline	-	Initial evaluation	full_test
2026-10-19T10:05	code-review-checklist	78	84	keep	Boundary conditions	Added fallback	full_test
2026-10-19T10:10	code-review-checklist	84	82	revert	Instruction specificity	Over-refined	dry_run
```

`eval_mode` column: `full_test` (subagent ran prompts) | `dry_run` (simulated reasoning, for reference only)

File location: `~/.pi/agent/skills/evolution-results.log`

---

## High-Leverage Operations (Quick Reference)

4 rules verified in practice:

- **HL-1 (dim4) Visual markers are leverage**: Add 🔴 CHECKPOINT / 🛑 STOP, relying on "must" wording doesn't work — LLM parses by scanning visual markers. 4 line changes drive dim4 +3 points
- **HL-2 (dim3) If-then three-part fallback table**: Upgrade "symptom/solution" two columns to "trigger condition / first-line fix / still-failed fallback" three-part structure. SkillLens failure-mechanism encoding dimension implementation
- **HL-3 (Phase 2 diagnosis) Dimension correlation cluster warning**: dim2/3/4 are correlated cluster — when fixing dim3, dim2 often rises too. When "finding largest weighted gap dimension", also look at correlation cluster gaps to decide whether to fix simultaneously
- **HL-4 (Phase 2 exit) Auto-break at ceiling**: Consecutive 2 rounds Δ < 2 points → break to Phase 3. +0.15 is a stop signal not a continue signal; forcing MAX_ROUNDS=3 introduces over-engineering

---

## Optimization Strategy Library

Prioritized, each round only does the highest priority one:

### P0: Effectiveness Issues (discovered through testing)
- Test output deviates from user intent → check if skill has misleading instructions
- With skill is worse than without → skill may be over-constraining, consider simplifying
- Output format doesn't match expectations → add explicit output template

### P1: Structural Issues
- Frontmatter missing trigger words → add Chinese/English trigger words
- Missing Phase/Step structure → reorganize into linear flow
- Missing user confirmation checkpoints → insert at critical decision points

### P2: Specificity Issues
- Steps are vague ("process images") → change to specific operations and parameters
- Missing input/output specifications → add format, path, examples
- Missing exception handling → add "if X fails, then Y"

### P3: Readability Issues
- Paragraphs too long → split + use tables
- Repeated descriptions → merge and deduplicate
- Missing quick reference → add TL;DR or decision tree

---

## Evolution Anti-Pattern Blacklist (dim9 Application: What Darwin Shouldn't Do When Optimizing)

| # | Anti-pattern | Why not to do | Alternative |
|---|---|---|---|
| 1 | **Self-evaluating in same context** | Scoring immediately after editing in same session has "what I just changed must be better" optimistic bias | Must use **before/after comparison**; keep/revert uses **comparison** (same judge reads before+after at once), **not absolute score delta** |
| 2 | **Using absolute score delta as keep/revert ratchet** | Absolute total score is sampling not measurement; baseline judge and rescore judge use different "scale", difference is mostly scale change, not real quality change | Absolute scores only for triage ranking; keep/revert uses before/after comparison |
| 3 | **Adding redundancy to chase score** | Continuing to force changes after ceiling is often "adding filler/paragraphs to make LLM think it's more detailed", actual quality unchanged | Ceiling signal (consecutive 2 rounds Δ<2 points) → break to Phase 3, **stop while ahead** |
| 4 | **Skipping test-prompts then scoring** | dim8 without test-prompts is scoring from thin air, weight 23% equals fabrication | Phase 0.5 forces design of 2-3 prompts; if user doesn't provide, default to creating 3 |
| 5 | **Changing multiple dimensions per round** | Multiple variables changing simultaneously, score rises/falls can't be attributed to specific changes | 1 dimension per round; correlated cluster (dim2/3/4) — when changing one, observe if others follow |
| 6 | **Dry run ratio > 30%** | dim8 effectiveness dimension becomes useless, scores artificially high | Force at least 1 real full_test; optimizations with many dry_runs marked ⚠️ in results log |
| 7 | **Ignoring dimension correlation when optimizing alone** | dim2/3/4 are correlated cluster, when optimizing dim2 alone often find it's already been pushed to ceiling by previous dim3 fix | When finding largest weighted gap dimension, also look at correlation cluster gaps, decide whether to fix simultaneously |

**Trigger scenario**: Check this table once before each Phase 2 change. Any anti-pattern hit → rewrite the plan.

---

## Constraints

1. **Don't change skill's core function or purpose** — only optimize "how to write" and "how to execute", not "what to do"
2. **Don't introduce new dependencies** — don't add scripts or references files the skill didn't originally have
3. **Only change one dimension per round** — avoid multiple changes making attribution impossible
4. **Keep file size reasonable** — optimized SKILL.md shouldn't exceed 150% of original size
5. **Reversible** — all changes can be rolled back (use file backup or git if available)
6. **Scoring independence** — effectiveness dimension must use subagent or at least dry run verification, can't "edit then immediately score" in same context

---

## Common Evolution Patterns

| Symptom | Likely dimension | Fix |
|---------|-----------------|-----|
| Agent skips the skill | Trigger accuracy (#6) | Rewrite triggers to match real situations |
| Agent follows skill but gets wrong result | Constraint completeness (#2) | Add missing must-do/must-not-do rules |
| Agent misinterprets instructions | Prompt executability (#8) | Remove ambiguity, add concrete examples |
| Skill never gets loaded | Tag coverage (#7) | Add more keywords agents would search for |
| Skill lacks failure handling | Failure mode encoding (#3) | Add explicit "if X fails → Y" branches |
| Instructions too vague | Executable specificity (#5) | Replace "suggest/could" with specific parameters |

---

## Version Bumping

- **Patch** (0.1.0 → 0.1.1): fix typos, add missing constraints, clarify wording
- **Minor** (0.1.0 → 0.2.0): restructure workflow, add new sections, change triggers
- **Major** (1.0.0 → 2.0.0): fundamental rewrite (rare)

---

## Credits

- **SkillLens** (arXiv [2605.23899](https://arxiv.org/abs/2605.23899)): 9-dimension rubric empirical source
- **darwin-skill** ([github.com/alchaincyf/darwin-skill](https://github.com/alchaincyf/darwin-skill)): Original inspiration for autonomous skill optimization
- **autoresearch** ([github.com/karpathy/autoresearch](https://github.com/karpathy/autoresearch)): Original inspiration for autonomous experiment loops
