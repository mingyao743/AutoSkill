/**
 * AutoSkill4Pi — Pi Coding Agent extension (agent-driven skill learning)
 *
 * Architecture:
 *   1. before_agent_start → inject current skill summary + extraction guidance
 *      into system prompt so the agent knows its skills and when to create new ones.
 *   2. Agent decides when to extract/evolve skills by calling tools:
 *      - autoskill_create: create a new skill (triggers darwin-skill evolution)
 *      - autoskill_update: update an existing skill
 *      - autoskill_list:   list current skills
 *      - autoskill_search: search skills by query (read-only)
 *   3. Tools spawn Python runtime for SkillBank CRUD + mirror.
 *   4. No bridge needed — agent IS the extraction engine.
 *
 * Lifecycle:
 *   - session_start:      initialize (optional legacy process-dir for migration)
 *   - before_agent_start: inject skill context into system prompt
 *   - session_shutdown:   cleanup
 */

import { spawn } from "node:child_process";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const AUTOSKILL_HOME = process.env["AUTOSKILL_PI_HOME"] || "~/.pi/autoskill";
const REPO_DIR = process.env["AUTOSKILL_PI_REPO_DIR"] || "";
const PYTHON = process.env["AUTOSKILL_PI_PYTHON"] || "python3";

// ---- System prompt injection: skill summary + extraction guidance ----

const SKILL_LEARNING_GUIDANCE = `
### Skill Learning (AutoSkill)

You have the ability to learn and reuse skills across sessions.

**When to create a skill (call autoskill_create):**
- User corrects your approach ("no, it should be...", "wrong, change to...")
- User establishes a reusable rule ("from now on, always...", "the format should be...")
- User expresses a clear preference ("don't use...", "prefer...")
- You discover a reusable pattern that would be hard to re-derive

**Skill naming rules:**
- name: ALWAYS English kebab-case (e.g., "code-review-checklist", "formal-report-style")
- description/prompt/triggers/tags: match user's language

**Skill prompt structure:**
- # Goal (required): what this skill achieves
- # Constraints & Style (required): must-do and must-not-do rules
- # Workflow (optional): only for explicit multi-step operations

**When to update a skill (call autoskill_update):**
- An existing skill is not working well for the current task
- User corrects something covered by an existing skill
- Call autoskill_update with the skill_id and fields to change

**When to search skills (call autoskill_search):**
- Before starting a task, check if you have a relevant skill
- When user references a previous pattern or rule
`;

function buildSkillInjectionPrompt(skillsJson: string): string {
  let skills: Array<{ name: string; description: string; version: string }> = [];
  try {
    skills = JSON.parse(skillsJson);
  } catch {
    // If we can't parse, just return the guidance without skill list
  }

  let skillList = "";
  if (skills.length > 0) {
    skillList = "\n**Your current skills:**\n";
    for (const s of skills) {
      skillList += `- ${s.name} (v${s.version}): ${s.description}\n`;
    }
  } else {
    skillList = "\nYou have no skills yet. Create your first one when you learn something reusable.\n";
  }

  return SKILL_LEARNING_GUIDANCE + skillList;
}

// ---- Python runtime invocation ----

function runPythonCapture(cmd: string[], extraEnv: Record<string, string> = {}): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!REPO_DIR) return reject(new Error("AUTOSKILL_PI_REPO_DIR not set"));
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      ...extraEnv,
    };
    const child = spawn(PYTHON, ["-m", "AutoSkill4Pi.runtime.pi_runtime", ...cmd], {
      cwd: REPO_DIR,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (b) => (out += b.toString()));
    child.stderr.on("data", (b) => (err += b.toString()));
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve(out.trim());
      else reject(new Error(`exit ${code}: ${err.slice(-500)}`));
    });
  });
}

function runPiRuntimeAsync(ctx: ExtensionContext, cmd: string[]) {
  if (!REPO_DIR) {
    ctx.ui.notify("AutoSkill: AUTOSKILL_PI_REPO_DIR not set", "warn");
    return;
  }
  const child = spawn(PYTHON, ["-m", "AutoSkill4Pi.runtime.pi_runtime", ...cmd], {
    cwd: REPO_DIR,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let out = "";
  child.stdout.on("data", (b) => (out += b.toString()));
  child.stderr.on("data", (b) => (out += b.toString()));
  child.on("close", (code) => {
    if (code !== 0) {
      ctx.ui.notify(`AutoSkill runtime failed (exit ${code}): ${out.slice(-300)}`, "warn");
    }
  });
  child.on("error", (e) => ctx.ui.notify(`AutoSkill runtime spawn failed: ${e.message}`, "warn"));
}

export default function (pi: ExtensionAPI) {
  // ---- Lifecycle hooks ----

  pi.on("session_start", async (_event, ctx) => {
    // Optional: run a legacy migration if needed (process any unprocessed sessions)
    // This is a one-time thing; after migration, agent-driven learning takes over.
  });

  pi.on("before_agent_start", async (_event, ctx) => {
    // Inject skill summary + extraction guidance into system prompt
    try {
      const skillsJson = await runPythonCapture(["list-skills", "--format", "json"]);
      const injection = buildSkillInjectionPrompt(skillsJson);
      // Return system prompt addition that Pi will merge
      return { systemPrompt: injection };
    } catch {
      // If we can't read skills, just inject the guidance without skill list
      return { systemPrompt: SKILL_LEARNING_GUIDANCE + "\n(Could not load skill list)\n" };
    }
  });

  pi.on("session_shutdown", async () => {
    // Nothing to clean up (no bridge)
  });

  // ---- Slash commands ----

  pi.registerCommand("autoskill_list", {
    description: "List all AutoSkill skills",
    handler: async (_args, ctx) => {
      try {
        const out = await runPythonCapture(["list-skills", "--format", "text"]);
        ctx.ui.notify(out || "(no skills)", "info");
      } catch (e: any) {
        ctx.ui.notify(`AutoSkill: ${e.message}`, "warn");
      }
    },
  });

  pi.registerCommand("autoskill_sync", {
    description: "Re-mirror SkillBank to ~/.pi/agent/skills",
    handler: async (_args, ctx) => {
      runPiRuntimeAsync(ctx, ["mirror"]);
      ctx.ui.notify("AutoSkill: mirroring skills...", "info");
    },
  });

  // ---- Tools ----

  pi.registerTool({
    name: "autoskill_create",
    description: "Create a new reusable skill from what you just learned. Use when the user corrects you, establishes a rule, or expresses a preference that should be reused.",
    parameters: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "English kebab-case name (e.g., 'code-review-checklist')",
        },
        description: {
          type: "string",
          description: "1-2 sentences: what this skill does and when to use it",
        },
        prompt: {
          type: "string",
          description: "Skill prompt with # Goal, # Constraints & Style, optional # Workflow",
        },
        triggers: {
          type: "array",
          items: { type: "string" },
          description: "3-5 intent phrases that trigger this skill",
        },
        tags: {
          type: "array",
          items: { type: "string" },
          description: "1-6 keywords",
        },
      },
      required: ["name", "description", "prompt"],
    },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
    execute: async (args: any, ctx: ExtensionContext) => {
      const payload = JSON.stringify({
        name: args.name,
        description: args.description,
        prompt: args.prompt,
        triggers: args.triggers || [],
        tags: args.tags || [],
      });
      try {
        const out = await runPythonCapture(["create-skill", "--payload", payload]);
        const result = JSON.parse(out);
        const skillId = result.skill_id || "";
        const version = result.version || "0.1.0";
        const evolved = result.evolution_applied ? " (evolved by darwin-skill)" : "";
        return {
          content: [{ type: "text", text: `Skill created: ${args.name} (v${version})${evolved}\nID: ${skillId}` }],
          details: undefined,
        };
      } catch (e: any) {
        return {
          content: [{ type: "text", text: `Failed to create skill: ${e.message}` }],
          details: undefined,
          isError: true,
        };
      }
    },
  });

  pi.registerTool({
    name: "autoskill_update",
    description: "Update an existing skill. Use when a skill is not working well or user corrects something covered by it.",
    parameters: {
      type: "object",
      properties: {
        skill_id: { type: "string", description: "ID of the skill to update" },
        name: { type: "string", description: "New name (optional)" },
        description: { type: "string", description: "New description (optional)" },
        prompt: { type: "string", description: "New prompt (optional)" },
        triggers: { type: "array", items: { type: "string" }, description: "New triggers (optional)" },
        tags: { type: "array", items: { type: "string" }, description: "New tags (optional)" },
      },
      required: ["skill_id"],
    },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
    execute: async (args: any, ctx: ExtensionContext) => {
      const payload = JSON.stringify({
        skill_id: args.skill_id,
        name: args.name,
        description: args.description,
        prompt: args.prompt,
        triggers: args.triggers,
        tags: args.tags,
      });
      try {
        const out = await runPythonCapture(["update-skill", "--payload", payload]);
        const result = JSON.parse(out);
        const version = result.version || "0.1.0";
        return {
          content: [{ type: "text", text: `Skill updated: ${result.name} (v${version})` }],
          details: undefined,
        };
      } catch (e: any) {
        return {
          content: [{ type: "text", text: `Failed to update skill: ${e.message}` }],
          details: undefined,
          isError: true,
        };
      }
    },
  });

  pi.registerTool({
    name: "autoskill_list",
    description: "List all your current skills with their IDs, names, and descriptions.",
    parameters: {
      type: "object",
      properties: {},
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    execute: async (_args: any, ctx: ExtensionContext) => {
      try {
        const out = await runPythonCapture(["list-skills", "--format", "text"]);
        return { content: [{ type: "text", text: out || "(no skills)" }], details: undefined };
      } catch (e: any) {
        return {
          content: [{ type: "text", text: `Failed to list skills: ${e.message}` }],
          details: undefined,
          isError: true,
        };
      }
    },
  });

  pi.registerTool({
    name: "autoskill_search",
    description: "Search your skills by keyword. Use before starting a task to check if you have a relevant skill.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search query" },
      },
      required: ["query"],
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    execute: async (args: any, ctx: ExtensionContext) => {
      const query = String(args?.query || "").trim();
      if (!query) {
        return { content: [{ type: "text", text: "query cannot be empty" }], details: undefined, isError: true };
      }
      try {
        const out = await runPythonCapture(["search", "--query", query]);
        return { content: [{ type: "text", text: out || "(no matching skills)" }], details: undefined };
      } catch (e: any) {
        return {
          content: [{ type: "text", text: `Search failed: ${e.message}` }],
          details: undefined,
          isError: true,
        };
      }
    },
  });
}
