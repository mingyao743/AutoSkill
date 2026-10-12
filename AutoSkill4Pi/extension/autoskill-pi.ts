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
 * 关于模型复用 API(已按本地安装的 @earendil-works/pi-ai / pi-coding-agent 类型核对):
 *   Pi 的 ModelRegistry 暴露 streamSimple(model, context, options?) -> AssistantMessageEventStream,
 *   并自带 request-time 鉴权;getApiKeyAndHeaders(model) -> Promise<ResolvedRequestAuth> 用于显式
 *   解析 key/header。callPiModel() 即据此实现,复用 ctx.model + ctx.modelRegistry,无需 import pi-ai。
 *   备选:不启用 bridge,直接设置 AUTOSKILL_PI_LLM_BASE_URL 为任意 OpenAI 兼容端点,
 *   此时 extension 尊重用户配置、不再注入内置 bridge(见 applyLlmBridgeEnv)。
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

// ---- LLM 路由策略:默认走内置 bridge(复用 Pi 当前模型),用户自配外部端点时尊重其配置 ----
function userConfiguredExternalLlm(): boolean {
  // 只要用户在环境里显式配了 AUTOSKILL_PI_LLM_BASE_URL,就视为“自配外部 OpenAI 兼容端点”。
  // bridge 的 URL 是每个进程随机端口、不会出现在父进程 env 里,因此不会误判。
  return Boolean((process.env["AUTOSKILL_PI_LLM_BASE_URL"] || "").trim());
}

function applyLlmBridgeEnv(env: NodeJS.ProcessEnv): void {
  if (userConfiguredExternalLlm()) {
    // 用户已自配外部端点:尊重其 AUTOSKILL_PI_LLM_PROVIDER/BASE_URL/API_KEY/MODEL
    // (这些已由 ...process.env 继承进来),不覆盖、不注入 bridge。
    return;
  }
  // 默认:把 AutoSkill 抽取 LLM 路由到内置 bridge,复用 Pi 当前模型 + key,无需单独配凭据。
  env["AUTOSKILL_PI_LLM_PROVIDER"] = "generic";
  env["AUTOSKILL_PI_LLM_BASE_URL"] = `http://${BRIDGE_HOST}:${bridgePort}/v1`;
  if (!env["AUTOSKILL_PI_LLM_MODEL"]) env["AUTOSKILL_PI_LLM_MODEL"] = "pi-current-model";
}

// ---- 触发一次后台处理:让 Python 扫 sessions 目录,账本幂等去重 ----
function runPiRuntime(ctx: ExtensionContext, cmd: string[], extraEnv: Record<string, string>) {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    AUTOSKILL_PI_SESSIONS_DIR: PI_SESSIONS_ROOT,
  };
  applyLlmBridgeEnv(env);
  Object.assign(env, extraEnv);
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
  // 复用 Pi 当前选定的模型 + provider 做抽取。
  // 真实 Pi API: ctx.modelRegistry.streamSimple(model, context, options?) -> AssistantMessageEventStream
  //   - model   : ctx.model(当前会话选中的模型,可能为 undefined)
  //   - context : { systemPrompt?, messages: Message[], tools? }(pi-ai Context)
  //   - options : { signal?, apiKey?, headers? }(streamSimple 内部自带 request-time 鉴权)
  //   - 返回事件流;text_delta 事件带 `delta: string`。
  const model: any = (ctx as any).model;
  if (!model) {
    throw new Error("AutoSkill: Pi 尚未选定模型(ctx.model 为空),无法复用 Pi 模型做抽取。");
  }
  const registry: any = (ctx as any).modelRegistry;
  if (!registry || typeof registry.streamSimple !== "function") {
    throw new Error("AutoSkill: ctx.modelRegistry.streamSimple 不可用(请核对当前 Pi 版本)。");
  }

  // 把 OpenAI chat/completions body 转成 pi-ai Context(system 抽为 systemPrompt,其余按 user/assistant)。
  const messages = Array.isArray(body?.messages) ? body.messages : [];
  const toText = (c: any): string =>
    typeof c === "string" ? c : Array.isArray(c) ? c.map((p: any) => p?.text ?? "").join("") : "";
  const systemMsg = messages.find((m: any) => m?.role === "system");
  const piMessages = messages
    .filter((m: any) => m?.role !== "system")
    .map((m: any) => ({
      role: m?.role === "assistant" ? "assistant" : "user",
      content: toText(m?.content),
    }));
  const context: any = {
    systemPrompt:
      (systemMsg ? toText(systemMsg.content) : "") ||
      "你是经验挖掘引擎(LLM 模式)。根据参考资料输出结果。",
    messages: piMessages,
  };

  // streamSimple 内部会做 request-time 鉴权;这里显式解析一次,缺凭据时给出明确错误,
  // 并把解析出的 apiKey/header 透传下去(如 OAuth header)。getApiKeyAndHeaders 返回 Promise。
  const options: any = { signal: (ctx as any).signal };
  if (typeof registry.getApiKeyAndHeaders === "function") {
    const auth: any = await registry.getApiKeyAndHeaders(model);
    if (auth && auth.ok === false) {
      throw new Error(`AutoSkill: Pi 模型鉴权失败: ${auth.error}`);
    }
    if (auth?.apiKey) options.apiKey = auth.apiKey;
    if (auth?.headers) options.headers = auth.headers;
  }

  // 消费事件流:累加 text_delta.delta 作为完整文本。
  const stream = registry.streamSimple(model, context, options) as AsyncIterable<any>;
  let collected = "";
  for await (const ev of stream) {
    if (ev?.type === "text_delta" && typeof ev.delta === "string") collected += ev.delta;
  }
  const out = collected.trim();
  if (!out) throw new Error("AutoSkill: Pi 模型返回空补全。");
  return out;
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
    // 仅当用户没有自配外部 LLM 端点时才起 bridge(避免多余监听)。
    if (!userConfiguredExternalLlm()) startBridge(ctx);
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
      AUTOSKILL_PI_SESSIONS_DIR: PI_SESSIONS_ROOT,
    };
    applyLlmBridgeEnv(env);
    const child = spawn(PYTHON, ["-m", "AutoSkill4Pi.runtime.pi_runtime", ...cmd], { cwd: REPO_DIR, env });
    let out = "";
    child.stdout.on("data", (b) => (out += b.toString()));
    child.stderr.on("data", (b) => (out += b.toString()));
    child.on("error", reject);
    child.on("close", () => resolve(out));
  });
}
