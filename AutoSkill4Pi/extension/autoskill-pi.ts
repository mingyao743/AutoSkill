/**
 * AutoSkill4Pi — Pi Coding Agent extension (运行形态 A: Extension adapter)
 *
 * 作用:
 *   1. 会话收口后(agent_settled)触发 AutoSkill 从 Pi 会话轨迹中抽取/演进技能;
 *   2. 复用 Pi 当前模型做抽取:extension 在本进程内起一个 localhost 的
 *      OpenAI 兼容 /v1/chat/completions bridge,内部转调 Pi 的模型运行时
 *      (ctx.modelRegistry.streamSimple),Python 侧用 provider=generic 指向它;
 *   3. 维护完成后把技能镜像到用户级 ~/.pi/agent/skills(由 Python 侧负责写盘);
 *   4. 提供 /autoskill_* 命令与 autoskill_search 工具用于运维与主动检索。
 *
 * 生命周期遵循 Pi 约定:
 *   - 不在 factory 里起 socket;bridge 从 session_start 启动;
 *   - session_shutdown 幂等关闭 server 与子进程。
 *
 * ⚠️ 需要在你第一次接入真实 Pi 时核对的唯一一点:
 *   callPiModel() 里对 ctx.modelRegistry.streamSimple(...) 的入参/返回签名。
 *   其余逻辑(session_start/agent_settled/session_shutdown 事件、registerCommand、
 *   registerTool、spawn python)均按官方 extensions.md 契约实现。
 *   若 streamSimple 形态不同,只需改 callPiModel() 一个函数。
 *   备选:不启用 bridge,直接设置 AUTOSKILL_PI_LLM_BASE_URL 为任意 OpenAI 兼容端点
 *   (config-resolve 回退),同样无需改动其它代码。
 */

import http from "node:http";
import { spawn } from "node:child_process";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const AUTOSKILL_HOME = process.env["AUTOSKILL_PI_HOME"] || "~/.pi/autoskill";
const PI_SESSIONS_ROOT = process.env["AUTOSKILL_PI_SESSIONS_DIR"] || "~/.pi/agent/sessions";
const REPO_DIR = process.env["AUTOSKILL_PI_REPO_DIR"] || ""; // AutoSkill 仓库 checkout 根
const PYTHON = process.env["AUTOSKILL_PI_PYTHON"] || "python3";
const BRIDGE_HOST = "127.0.0.1";

let bridgeServer: http.Server | null = null;
let bridgePort = 0;
let liveExtractCounter = 0;
const LIVE_EVERY_TURNS = Number(process.env["AUTOSKILL_PI_LIVE_EXTRACT_EVERY_TURNS"] || "0"); // 0=off

// ---- 触发一次后台处理:让 Python 扫 sessions 目录,账本幂等去重 ----
function runPiRuntime(ctx: ExtensionContext, cmd: string[], extraEnv: Record<string, string>) {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    AUTOSKILL_PI_LLM_PROVIDER: "generic",
    AUTOSKILL_PI_LLM_BASE_URL: `http://${BRIDGE_HOST}:${bridgePort}/v1`,
    AUTOSKILL_PI_LLM_MODEL: "pi-current-model",
    AUTOSKILL_PI_SESSIONS_DIR: PI_SESSIONS_ROOT,
    ...extraEnv,
  };
  if (!REPO_DIR) {
    ctx.ui.notify("AutoSkill: AUTOSKILL_PI_REPO_DIR 未设置,跳过本次抽取", "warn");
    return;
  }
  const child = spawn(PYTHON, ["-m", "AutoSkill4Pi.runtime.pi_runtime", ...cmd], {
    cwd: REPO_DIR,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let out = "";
  child.stdout.on("data", (b) => (out += b.toString()));
  child.stderr.on("data", (b) => out += b.toString());
  child.on("close", (code) => {
    if (code === 0) {
      try {
        const summary = JSON.parse(out.trim().split("\n").pop() || "{}");
        const n = Number(summary.upserted || 0);
        if (n > 0) ctx.ui.notify(`AutoSkill: 演进/新增 ${n} 个技能,已镜像到 ~/.pi/agent/skills`, "info");
      } catch {
        /* non-fatal */
      }
    } else {
      ctx.ui.notify(`AutoSkill runtime 失败 (exit ${code}): ${out.slice(-300)}`, "warn");
    }
  });
  child.on("error", (e) => ctx.ui.notify(`AutoSkill runtime 启动失败: ${e.message}`, "warn"));
}

// ---- Pi 模型 bridge:OpenAI 兼容 /v1/chat/completions -> Pi 当前模型 ----
async function callPiModel(ctx: ExtensionContext, body: any): Promise<string> {
  // ⚠️ 唯一需按真实 Pi API 对齐的调用点。以下为基于 extensions.md 的实现。
  // streamSimple 用于 provider 无关的嵌套模型调用;这里把 OpenAI messages 转成
  // Pi 可接受的输入并收集完整文本返回。
  const messages = Array.isArray(body?.messages) ? body.messages : [];
  const promptText = messages
    .map((m: any) => `${m.role}: ${typeof m.content === "string" ? m.content : (m.content || []).map((p: any) => p.text || "").join("")}`)
    .join("\n");

  const registry: any = (ctx as any).modelRegistry;
  if (!registry || typeof registry.streamSimple !== "function") {
    throw new Error("ctx.modelRegistry.streamSimple 不可用:请核对当前 Pi 版本的模型调用 API");
  }

  // 兼容两种可能签名:(1) 事件流 (2) 直接返回聚合结果
  let collected = "";
  const result = await registry.streamSimple({
    prompt: promptText,
    system: (messages.find((m: any) => m.role === "system") || {}).content,
    signal: ctx.signal,
    onEvent: (ev: any) => {
      if (ev && typeof ev.text === "string") collected += ev.text;
    },
  });
  if (typeof result === "string") collected = result;
  else if (result?.text) collected = String(result.text);
  else if (result?.content) collected = typeof result.content === "string" ? result.content : JSON.stringify(result.content);
  return collected;
}

function startBridge(ctx: ExtensionContext) {
  if (bridgeServer) return;
  bridgeServer = http.createServer((req, res) => {
    if (req.method === "GET" && req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
      return;
    }
    if (req.method === "POST" && /\/v1\/chat\/completions$/.test(req.url || "")) {
      let raw = "";
      req.on("data", (c) => (raw += c));
      req.on("end", async () => {
        try {
          const body = JSON.parse(raw || "{}");
          const text = await callPiModel(ctx, body);
          const resp = {
            id: "chatcmpl-autoskill",
            object: "chat.completion",
            model: body.model || "pi-current-model",
            choices: [{ index: 0, message: { role: "assistant", content: text }, finish_reason: "stop" }],
          };
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify(resp));
        } catch (e: any) {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: { message: String(e?.message || e) } }));
        }
      });
      return;
    }
    res.writeHead(404);
    res.end();
  });
  bridgeServer.listen(0, BRIDGE_HOST, () => {
    const addr = bridgeServer?.address();
    if (addr && typeof addr === "object") bridgePort = addr.port;
    ctx.ui.notify(`AutoSkill: Pi 模型 bridge 已启动 http://${BRIDGE_HOST}:${bridgePort}/v1`, "info");
  });
}

function stopBridge() {
  if (bridgeServer) {
    try { bridgeServer.close(); } catch { /* noop */ }
    bridgeServer = null;
    bridgePort = 0;
  }
}

export default function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    startBridge(ctx);
  });

  pi.on("session_shutdown", async () => {
    stopBridge();
  });

  // 会话最终收口:通知-only,适合触发一次完整抽取/维护。
  pi.on("agent_settled", async (_event, ctx) => {
    liveExtractCounter = 0;
    runPiRuntime(ctx, ["process-dir", "--dir", PI_SESSIONS_ROOT], {});
  });

  // 可选:活跃会话每 N turn 做一次 checkpoint 抽取(默认关闭)
  pi.on("turn_end", async (_event, ctx) => {
    if (LIVE_EVERY_TURNS <= 0) return;
    liveExtractCounter += 1;
    if (liveExtractCounter >= LIVE_EVERY_TURNS) {
      liveExtractCounter = 0;
      runPiRuntime(ctx, ["process-dir", "--dir", PI_SESSIONS_ROOT], { AUTOSKILL_PI_LIVE: "1" });
    }
  });

  pi.registerCommand("autoskill_extract_now", {
    description: "立即触发一次 AutoSkill 技能抽取/维护(扫描 Pi 会话)",
    handler: async (_args, ctx) => {
      runPiRuntime(ctx, ["process-dir", "--dir", PI_SESSIONS_ROOT], {});
    },
  });

  pi.registerCommand("autoskill_sync", {
    description: "重新把 SkillBank 镜像到 ~/.pi/agent/skills",
    handler: async (_args, ctx) => {
      runPiRuntime(ctx, ["mirror"], {});
    },
  });

  pi.registerTool({
    name: "autoskill_search",
    description: "在 AutoSkill 技能库中检索与当前任务相关的可复用技能(只读)。",
    parameters: {
      type: "object",
      properties: { query: { type: "string", description: "检索查询" } },
      required: ["query"],
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    execute: async (args: any, ctx: ExtensionContext) => {
      const query = String(args?.query || "").trim();
      if (!query) return { content: [{ type: "text", text: "query 不能为空" }], details: undefined, isError: true };
      // 走 Python:mirror 命令之外这里用一个轻量 search 输出。为保持简单,
      // 复用 pi_runtime 的 search 能力通过 SDK;若未接入则提示用 /autoskill_sync。
      const out = await runPythonCapture(ctx, ["search", "--query", query]).catch((e) => String(e));
      return { content: [{ type: "text", text: out || "(no matching skills)" }], details: undefined };
    },
  });
}

// 同步捕获 Python 子进程输出(用于工具检索)
function runPythonCapture(ctx: ExtensionContext, cmd: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!REPO_DIR) return reject(new Error("AUTOSKILL_PI_REPO_DIR 未设置"));
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      AUTOSKILL_PI_LLM_PROVIDER: "generic",
      AUTOSKILL_PI_LLM_BASE_URL: `http://${BRIDGE_HOST}:${bridgePort}/v1`,
      AUTOSKILL_PI_SESSIONS_DIR: PI_SESSIONS_ROOT,
    };
    const child = spawn(PYTHON, ["-m", "AutoSkill4Pi.runtime.pi_runtime", ...cmd], { cwd: REPO_DIR, env });
    let out = "";
    child.stdout.on("data", (b) => (out += b.toString()));
    child.stderr.on("data", (b) => (out += b.toString()));
    child.on("error", reject);
    child.on("close", () => resolve(out));
  });
}
