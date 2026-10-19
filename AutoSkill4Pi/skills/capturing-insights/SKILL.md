---
name: capturing-insights
description: Use when you discover an interesting pattern, workaround, or observation during work that may be worth preserving but isn't yet validated by user feedback
version: 0.2.0
triggers: [interesting pattern, workaround, non-obvious observation, might be reusable, not sure if generalizable, good explanation, complex solution]
tags: [insight capture, knowledge capture, flash note, observation]
---

# Capturing Insights

## Overview

Insights are lightweight observations captured during work — the raw material between session logs and mature skills. They lower the bar for knowledge capture: when something is interesting but not yet proven reusable, write an insight instead of a full skill.

**Core principle:** Don't lose observations. Capture first, refine later.

## When to Capture an Insight

**Capture when (unvalidated signals — need more evidence before becoming skill):**
- You discover a non-obvious pattern, but aren't sure if it generalizes
- You find a workaround that might be useful later
- You notice a recurring issue across tasks
- Something surprises you ("I didn't expect X to work that way")
- User mentions something in passing that might be important later
- You give an explanation or analysis that you think is good, but user hasn't confirmed yet
- You successfully solve a complex problem, but the solution might be context-specific

**Don't capture for:**
- Things already covered by an existing skill
- Trivial observations with no future relevance
- User corrections or clear rules → go directly to skill creation (already validated)
- User affirms your response with key additions → go directly to skill creation (already validated)

**Validation principle:**
- If user explicitly confirms/corrects → **validated** → create skill directly
- If you think something is interesting but user hasn't responded → **unvalidated** → write insight

## Insight vs Skill

| | Insight | Skill |
|---|---|---|
| Maturity | Raw observation | Proven reusable |
| Format | Minimal markdown | Structured SKILL.md |
| Effort | 30 seconds | 2-5 minutes |
| When | "This might be useful" | "This IS useful" |
| Location | `~/.pi/agent/insights/` | `~/.pi/agent/skills/` |

## Insight Format

Write to `~/.pi/agent/insights/<date>-<slug>.md`:

```markdown
# Brief title

- **Context**: What were you working on?
- **Observation**: What did you notice?
- **Why it matters**: Why might this be useful later?
- **Open questions**: What's still uncertain?
```

**Example:**

```markdown
# JSON parsing fails silently on trailing commas

- **Context**: Debugging user config loading
- **Observation**: Python json.loads() raises an error, but many users hand-edit JSON and add trailing commas. The error message doesn't point to the exact location.
- **Why it matters**: Could create a skill for "robust config parsing" with a pre-processing step to strip trailing commas.
- **Open questions**: Is this common enough to warrant a skill? Are there other JSON pitfalls worth including?
```

## Naming Convention

File name: `YYYY-MM-DD-<english-kebab-case-slug>.md`

Examples:
- `2026-10-19-json-trailing-commas.md`
- `2026-10-19-git-rebase-interactive-timeout.md`
- `2026-10-19-api-rate-limit-retry-pattern.md`

## Consolidation: Insights → Skills

When 3+ insights share a common theme, consolidate them into a skill:

1. **Review** related insights together
2. **Identify** the common pattern
3. **Create** a SKILL.md using the creating-skills guidance
4. **Reference** the source insights in the skill (optional)
5. **Archive** or delete the consolidated insights

**Trigger for consolidation:**
- You're about to create a skill and notice existing insights cover the same topic
- Periodic review (when user asks, or when insights accumulate)

## Workflow

1. Notice something interesting during work
2. Ask: "Is this already a skill? Is this a clear rule?"
   - Yes → follow existing skill / create skill directly
   - No → write an insight (30 seconds)
3. Continue working
4. Later: review insights, consolidate into skills when patterns emerge
