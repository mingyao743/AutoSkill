---
name: creating-skills
description: Use when creating new skills, editing existing skills, or when user corrects your approach, establishes reusable rules, or expresses clear preferences
version: 0.2.0
triggers: [create skill, edit skill, user correction, reusable rule, clear preference, repeated pattern]
tags: [skill creation, best practice, knowledge capture, learning]
---

# Creating Skills

## Overview

Skills are reusable reference guides stored as SKILL.md files. They help future sessions benefit from patterns, corrections, and preferences discovered in current sessions.

**Core principle:** If the user corrected you or stated a rule, capture it as a skill so future sessions don't repeat the mistake.

## When to Create

**Create when:**
- User corrects your approach ("no, it should be...", "wrong, change to...")
- User establishes a reusable rule ("from now on, always...")
- User expresses a clear preference ("don't use...", "prefer...")
- You discover a non-obvious pattern that took multiple tries to get right

**Don't create for:**
- One-off solutions specific to a single task
- Standard practices well-documented elsewhere
- Project-specific conventions (put in project instructions instead)

## SKILL.md Format

Write to `~/.pi/agent/skills/<skill-name>/SKILL.md`:

```markdown
---
name: english-kebab-case-name
description: Use when [specific triggering conditions and symptoms]
version: 0.1.0
triggers: [intent1, intent2, intent3]
tags: [keyword1, keyword2]
---

# Goal
What this skill achieves (1-2 sentences).

# Constraints & Style
Must-do and must-not-do rules.

# Workflow (optional)
Multi-step operations only.
```

## Naming Rules

**name field:**
- ALWAYS English kebab-case (e.g., `code-review-checklist`, `async-error-handling`)
- Use letters, numbers, hyphens only (no parentheses, special chars)
- Prefer gerunds (-ing) for processes: `creating-skills` > `skill-creation`
- Active voice, verb-first when possible

**Other fields (description/triggers/tags):**
- Match the user's language (Chinese input → Chinese fields)
- description: start with "Use when..." or equivalent, describe ONLY triggering conditions
- NEVER summarize the skill's workflow in description (agents will take the shortcut and skip the skill body)

## Description Field (Critical for Discovery)

**Purpose:** Future agents read description to decide whether to load this skill.

**Format:** Triggering conditions only, NOT what the skill does.

```yaml
# BAD: Summarizes workflow (agents will follow this instead of reading skill)
description: Use when reviewing code - check imports, then logic, then tests, then docs

# BAD: Too vague
description: For code review

# GOOD: Triggering conditions only
description: Use when reviewing pull requests or before merging code changes
```

**Why this matters:** When description summarizes workflow, agents may follow the description instead of reading the full skill content. A description saying "code review between tasks" caused an agent to do ONE review, even though the skill's flowchart clearly showed TWO reviews.

**The trap:** Descriptions that summarize workflow create a shortcut agents will take. The skill body becomes documentation agents skip.

## Keyword Coverage

Include words agents would search for:
- Error messages or symptoms: "flaky", "timeout", "race condition"
- Tools: actual commands, library names
- Synonyms: cover variations (timeout/hang/freeze)

## Conciseness (Critical)

**Target:** < 200 words for frequently-loaded skills, < 500 for others.

**Default assumption:** Agents are already very smart. Only add context they don't already have.

Challenge each piece of information:
- "Does the agent really need this explanation?"
- "Can I assume the agent knows this?"
- "Does this paragraph justify its token cost?"

**Good example (50 tokens):**
```markdown
## Extract PDF text
Use pdfplumber for text extraction:
```python
import pdfplumber
with pdfplumber.open("file.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```
```

**Bad example (150 tokens):**
```markdown
## Extract PDF text
PDF (Portable Document Format) files are a common file format that contains
text, images, and other content. To extract text from a PDF, you'll need to
use a library. There are many libraries available for PDF processing, but we
recommend pdfplumber because it's easy to use and handles most cases well...
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Description summarizes workflow | Rewrite to describe only triggering conditions |
| Name in user's language | Always English kebab-case for name field |
| Vague triggers ("for testing") | Be specific: "Use when tests have race conditions" |
| Narrative storytelling | Extract the reusable pattern, discard the story |
| Multiple languages for examples | Pick one, make it excellent |
| Too verbose | Assume agent is smart, remove obvious explanations |
| Deeply nested references | Keep references one level deep from SKILL.md |

## Workflow

1. Detect signal (correction/rule/preference)
2. Choose name (English kebab-case, gerund if process)
3. Write description (triggering conditions only, user's language)
4. Write body (Goal + Constraints & Style + Workflow if needed)
5. Create directory and write file using your file tools
6. Verify: would a future agent find this when facing the same problem?

## Iterative Improvement

Skills improve through real usage, not upfront perfection:

1. **Create minimal skill** addressing the specific correction/rule
2. **Use in real tasks** — observe if future sessions apply it correctly
3. **Iterate based on observation** — if agent misses something, refine the skill
4. **Bump version** when making significant changes (0.1.0 → 0.1.1 for fixes, 0.1.0 → 0.2.0 for restructuring)

**Why this works:** You provide domain expertise, the agent reveals gaps through real usage, and iterative refinement improves skills based on observed behavior rather than assumptions.

## Checklist

Before finalizing a skill:

- [ ] Description starts with "Use when..." and includes specific triggers
- [ ] Description does NOT summarize workflow
- [ ] Name is English kebab-case (gerund preferred)
- [ ] SKILL.md body is concise (< 200 words for frequently-loaded)
- [ ] Keywords cover error messages, symptoms, synonyms
- [ ] No time-sensitive information
- [ ] Consistent terminology throughout
- [ ] Examples are concrete, not abstract
