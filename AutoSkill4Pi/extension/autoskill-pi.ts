/**
 * AutoSkill4Pi — Minimal Pi extension for agent-driven skill learning
 *
 * Architecture: Pure filesystem, zero Python, zero tools, zero bridge.
 *
 * - before_agent_start:
 *   1. Reads meta-skills from <REPO_DIR>/AutoSkill4Pi/skills/*/SKILL.md (full content)
 *      → these are "how to create/evolve/capture" guidance
 *   2. Reads user skills from ~/.pi/agent/skills/*/SKILL.md (frontmatter summary)
 *      → these are the agent's learned skills
 *   3. Reads recent insights from ~/.pi/agent/insights/*.md (title list)
 *      → these are raw observations not yet consolidated into skills
 *   4. Injects all into system prompt
 * - Agent uses Pi's native file tools to create/update/evolve skills and capture insights
 * - SKILL.md format is the only contract between extension and agent
 */

import fs from "node:fs";
import path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const REPO_DIR = process.env["AUTOSKILL_PI_REPO_DIR"] || "";
const PI_HOME = process.env["AUTOSKILL_PI_HOME"] || path.join(process.env["HOME"] || "~", ".pi/agent");
const PI_SKILLS_DIR = process.env["AUTOSKILL_PI_SKILLS_DIR"] || path.join(PI_HOME, "skills");
const PI_INSIGHTS_DIR = process.env["AUTOSKILL_PI_INSIGHTS_DIR"] || path.join(PI_HOME, "insights");
const META_SKILLS_DIR = REPO_DIR ? path.join(REPO_DIR, "AutoSkill4Pi", "skills") : "";

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

// ---- Read user skills (frontmatter summary only) ----

function readUserSkills(): SkillMeta[] {
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

// ---- Read meta-skills (full content for injection) ----

function readMetaSkills(): string[] {
  const contents: string[] = [];
  if (!META_SKILLS_DIR || !fs.existsSync(META_SKILLS_DIR)) return contents;
  for (const entry of fs.readdirSync(META_SKILLS_DIR, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const skillFile = path.join(META_SKILLS_DIR, entry.name, "SKILL.md");
    if (!fs.existsSync(skillFile)) continue;
    try {
      contents.push(fs.readFileSync(skillFile, "utf-8"));
    } catch { /* skip unreadable */ }
  }
  return contents;
}

// ---- Read insights (title + first line only) ----

interface InsightMeta {
  file: string;
  title: string;
}

function readInsights(): InsightMeta[] {
  const insights: InsightMeta[] = [];
  const dir = PI_INSIGHTS_DIR.replace("~", process.env["HOME"] || "~");
  if (!fs.existsSync(dir)) return insights;
  const files = fs.readdirSync(dir).filter((f) => f.endsWith(".md")).sort().reverse();
  for (const file of files.slice(0, 10)) {
    try {
      const content = fs.readFileSync(path.join(dir, file), "utf-8");
      const titleMatch = content.match(/^#\s+(.+)$/m);
      const title = titleMatch ? titleMatch[1].trim() : file.replace(".md", "");
      insights.push({ file, title });
    } catch { /* skip unreadable */ }
  }
  return insights;
}

// ---- System prompt injection ----

function buildInjection(userSkills: SkillMeta[], metaSkillContents: string[], insights: InsightMeta[]): string {
  const skillList = userSkills.length > 0
    ? userSkills.map((s) => `- ${s.name} (v${s.version}): ${s.description}`).join("\n")
    : "(no skills yet)";

  const metaGuidance = metaSkillContents.length > 0
    ? metaSkillContents.join("\n\n---\n\n")
    : "(meta-skills not found — set AUTOSKILL_PI_REPO_DIR to enable)";

  const insightList = insights.length > 0
    ? insights.map((i) => `- ${i.title} (${i.file})`).join("\n")
    : "(no insights yet)";

  return `
### Skill Learning (AutoSkill)

You can learn reusable skills by writing SKILL.md files to \`${PI_SKILLS_DIR}/<skill-name>/SKILL.md\`.
You can capture lightweight insights by writing markdown files to \`${PI_INSIGHTS_DIR}/\`.

**Your current skills:**
${skillList}

**Recent insights (raw observations, not yet skills):**
${insightList}

**Skill creation & evolution guidance:**

${metaGuidance}
`;
}

export default function (pi: ExtensionAPI) {
  pi.on("before_agent_start", async (_event, ctx: ExtensionContext) => {
    const userSkills = readUserSkills();
    const metaSkills = readMetaSkills();
    const insights = readInsights();
    return { systemPrompt: buildInjection(userSkills, metaSkills, insights) };
  });
}
