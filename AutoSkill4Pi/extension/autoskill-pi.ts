/**
 * AutoSkill4Pi — Minimal Pi extension for agent-driven skill learning
 *
 * Architecture: Pure filesystem, zero Python, zero tools, zero bridge.
 *
 * - before_agent_start: reads ~/.pi/agent/skills/*/SKILL.md, injects summary + guidance
 * - Agent uses Pi's native file tools to create/update/evolve skills
 * - SKILL.md format is the only contract between extension and agent
 */

import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const PI_SKILLS_DIR = process.env["AUTOSKILL_PI_SKILLS_DIR"] || path.join(process.env["HOME"] || "~", ".pi/agent/skills");

// ---- SKILL.md parser (extract frontmatter fields) ----

interface SkillMeta {
  name: string;
  description: string;
  version: string;
}

function parseSkillFrontmatter(content: string): SkillMeta {
  const meta: SkillMeta = { name: "", description: "", version: "0.1.0" };
  const fmMatch = content.match(/^---\n([\s\S]*?)\n---/);
  if (!fmMatch) return meta;
  const fm = fmMatch[1];
  const getName = fm.match(/^name:\s*(.+)$/m);
  const getDesc = fm.match(/^description:\s*(.+)$/m);
  const getVer = fm.match(/^version:\s*(.+)$/m);
  if (getName) meta.name = getName[1].replace(/^["']|["']$/g, "").trim();
  if (getDesc) meta.description = getDesc[1].replace(/^["']|["']$/g, "").trim();
  if (getVer) meta.version = getVer[1].replace(/^["']|["']$/g, "").trim();
  return meta;
}

// ---- Read all skills from directory ----

function readSkills(): SkillMeta[] {
  const skills: SkillMeta[] = [];
  const dir = PI_SKILLS_DIR.replace("~", process.env["HOME"] || "~");
  if (!fs.existsSync(dir)) return skills;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const skillFile = path.join(dir, entry.name, "SKILL.md");
    if (!fs.existsSync(skillFile)) continue;
    try {
      const content = fs.readFileSync(skillFile, "utf-8");
      const meta = parseSkillFrontmatter(content);
      if (meta.name) skills.push(meta);
    } catch { /* skip unreadable */ }
  }
  return skills;
}

// ---- System prompt injection ----

function buildInjection(skills: SkillMeta[]): string {
  const skillList = skills.length > 0
    ? skills.map((s) => `- ${s.name} (v${s.version}): ${s.description}`).join("\n")
    : "(no skills yet)";

  return `
### Skill Learning (AutoSkill)

You can learn reusable skills by writing SKILL.md files to \`${PI_SKILLS_DIR}/<skill-name>/SKILL.md\`.

**Your current skills:**
${skillList}

**When to create a skill:**
- User corrects your approach ("no, it should be...", "wrong, change to...")
- User establishes a reusable rule ("from now on, always...")
- User expresses a clear preference ("don't use...", "prefer...")
→ Create directory and write SKILL.md using your file tools.

**SKILL.md format:**
\`\`\`
---
name: english-kebab-case-name
description: 1-2 sentences, what and when
version: 0.1.0
triggers: [intent1, intent2, intent3]
tags: [keyword1, keyword2]
---
# Goal
What this skill achieves.
# Constraints & Style
Must-do and must-not-do rules.
# Workflow (optional)
Multi-step operations only.
\`\`\`

**Naming rules:**
- name: ALWAYS English kebab-case (e.g., "code-review-checklist")
- description/prompt/triggers/tags: match user's language

**When to update a skill:**
- Skill doesn't work well, user corrects again
→ Edit the SKILL.md file directly, bump version.

**When to evolve a skill (apply darwin-skill 9-dimension evaluation):**
- Skill used many times but still gets corrections
→ Read the skill, evaluate: goal clarity, constraint completeness, workflow reasonability, reusability, de-identification, trigger accuracy, tag coverage, prompt executability, anti-pattern check.
→ Rewrite SKILL.md with improvements.
`;
}

export default function (pi: ExtensionAPI) {
  pi.on("before_agent_start", async () => {
    const skills = readSkills();
    return { systemPrompt: buildInjection(skills) };
  });
}
