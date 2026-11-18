import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { spawn } from "node:child_process";
import { realpath } from "node:fs/promises";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { Type } from "typebox";
import { Text, truncateToWidth } from "@earendil-works/pi-tui";

type Stage = "clarify" | "plan" | "execute" | "verify";
type Scope = { requirement: string; stage: Stage; task?: string; node?: string; parent?: string };
type AuditItem = { name: string; source: string; summary?: string; evidence?: string; node?: string; kind?: string; limitation?: string; stage?: Stage; parent?: string; task?: string; id?: string; recorded_text_sha256?: string };
type Board = {
  requirement: string; title: string;
  tasks: { task: string; title: string; state: string; after?: string[]; blocker?: string; children: { requirement: string; warning?: string }[] }[];
  superiors: { requirement: string; task: string; entry: string }[];
  inputs: AuditItem[]; outputs: AuditItem[]; skills: AuditItem[]; rules: AuditItem[]; nodes: AuditItem[]; warnings: string[];
};
type Observed = { kind: string; name: string; source: "pi-read" | "pi-command" | "pi-event"; summary?: string; detail?: unknown; node?: string; parent?: string; run?: string };

const workflow = fileURLToPath(new URL("../workflow.py", import.meta.url));
const validRequirement = /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/;
const validTask = /^T[0-9]{2,}$/;
const stageType = Type.Union([Type.Literal("clarify"), Type.Literal("plan"), Type.Literal("execute"), Type.Literal("verify")]);

export default function (pi: ExtensionAPI) {
  let scope: Scope | undefined;
  let pendingCommand: string | undefined;
  let pendingInput: { prompt: string; files: { path: string; content: string }[] } | undefined;
  let initialSkill: Observed | undefined;
  let run: string | undefined;
  let queue = Promise.resolve();
  let lifetime = new AbortController();
  const calls = new Map<string, { scope: Scope; input: unknown; observedInput: boolean; parent?: string; run?: string; owner: AbortController }>();
  const pending = new Set<{ scope: Scope; node?: string }>();

  function request(args: string[], cwd: string, payload?: unknown, signal = lifetime.signal): Promise<string> {
    return new Promise((done, reject) => {
      const child = spawn("python3", [workflow, ...args], { cwd, stdio: ["pipe", "pipe", "pipe"], signal });
      const timer = setTimeout(() => child.kill("SIGTERM"), 15000);
      let stdout = "", stderr = "", overflow = false;
      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", chunk => {
        stdout += chunk;
        if (Buffer.byteLength(stdout) > 4 * 1024 * 1024) { overflow = true; child.kill("SIGTERM"); }
      });
      child.stderr.on("data", chunk => { stderr = (stderr + chunk).slice(-16000); });
      child.on("error", error => { clearTimeout(timer); reject(error); });
      child.on("close", code => {
        clearTimeout(timer);
        if (code !== 0 || overflow) reject(new Error(overflow ? "审计输出过大，请使用CLI逐项深审" : stderr.trim() || "审计操作未完成"));
        else done(stdout);
      });
      child.stdin.on("error", () => {});
      child.stdin.end(payload === undefined ? undefined : JSON.stringify(payload));
    });
  }

  function warn(ctx: ExtensionContext, error: unknown, current?: Scope, node?: string) {
    const text = String(error).replace(/[\x00-\x1f\x7f]/g, " ").slice(0, 240);
    if (ctx.hasUI) ctx.ui.setStatus("ai-workflow-audit", `审计不完整：${text}`);
    pi.appendEntry("ai-workflow-audit-gap", { scope: current ?? scope, node, message: text });
  }

  async function observe(event: Observed, current: Scope, ctx: ExtensionContext) {
    const payload = { ...event, stage: current.stage, task: current.task,
      node: event.node ?? current.node, parent: event.parent ?? current.parent, run: event.run ?? run };
    const owner = lifetime;
    const item = { scope: current, node: event.node };
    pending.add(item);
    const recording = queue.then(() => {
      if (owner.signal.aborted) return;
      return request(["_observe-event", current.requirement], ctx.cwd, payload, owner.signal);
    }).then(() => {});
    queue = recording.catch(() => {});
    try { await recording; }
    catch (error) { if (!owner.signal.aborted) warn(ctx, error, current, event.node); }
    finally { pending.delete(item); }
  }

  async function recordAgent(current: Scope, ctx: ExtensionContext) {
    if (!run) return;
    await observe({ kind: "agent", name: "当前会话Agent", source: "pi-event", node: run,
      parent: current.node, run, summary: "真实会话运行；跨节点保持同一Agent身份，不是独立子Agent",
      detail: { session: ctx.sessionManager.getSessionId(), observation: "agent_start" } }, current, ctx);
  }

  async function inputs(current: Scope, ctx: ExtensionContext) {
    if (!pendingInput) return;
    await observe({ kind: "input", name: "Pi触发输入", source: "pi-event", summary: "本轮实际观察到的用户输入；不代表完整provider请求",
      detail: { prompt: pendingInput.prompt, observation: "before_agent_start，后续扩展仍可能修改上下文" } }, current, ctx);
    for (const file of pendingInput.files) {
      await observe({ kind: "rule", name: file.path, source: "pi-event", summary: "Pi系统上下文中实际加载的规则",
        detail: { path: file.path, content: file.content, observation: "systemPromptOptions.contextFiles；未重读磁盘" } }, current, ctx);
    }
  }

  function restore(ctx: ExtensionContext) {
    scope = undefined;
    pendingInput = undefined;
    pendingCommand = undefined;
    initialSkill = undefined;
    run = undefined;
    calls.clear();
    pending.clear();
    const entries = ctx.sessionManager.getBranch();
    for (const entry of entries) {
      if (entry.type !== "custom" || entry.customType !== "ai-workflow-scope") continue;
      const saved = entry.data as { scope?: Scope; cwd?: string } | undefined;
      scope = undefined;
      if (saved?.cwd === ctx.cwd && saved.scope && validRequirement.test(saved.scope.requirement)
          && ["clarify", "plan", "execute", "verify"].includes(saved.scope.stage)
          && (!saved.scope.task || validTask.test(saved.scope.task))) scope = { ...saved.scope };
    }
    if (ctx.hasUI) {
      const gap = [...entries].reverse().find(entry => entry.type === "custom" && entry.customType === "ai-workflow-audit-gap");
      ctx.ui.setStatus("ai-workflow-audit", gap ? "审计不完整：当前分支保留观察缺口记录" : undefined);
      ctx.ui.setStatus("ai-workflow", scope ? `${scope.requirement}${scope.task ? "/" + scope.task : ""} · ${scope.stage}` : undefined);
    }
  }

  pi.on("session_start", (_event, ctx) => {
    lifetime.abort();
    lifetime = new AbortController();
    queue = Promise.resolve();
    restore(ctx);
  });
  pi.on("session_tree", (_event, ctx) => restore(ctx));
  pi.on("session_shutdown", (_event, ctx) => {
    const reported = new Set<string>();
    for (const item of [...pending, ...[...calls].map(([node, call]) => ({ scope: call.scope, node }))]) {
      const key = `${item.scope.requirement}/${item.scope.task ?? ""}/${item.scope.stage}/${item.node ?? ""}`;
      if (!reported.has(key)) {
        warn(ctx, "会话结束时观察尚未落盘；原始工具结果仍在宿主会话中", item.scope, item.node);
        reported.add(key);
      }
    }
    lifetime.abort();
    calls.clear();
  });

  pi.registerTool({
    name: "ai_workflow_audit_context", label: "AIWorkflow 节点上下文",
    description: "Bind subsequent observed inputs, capabilities and tool results to an initialized workflow node.",
    parameters: Type.Object({ requirement: Type.String({ pattern: validRequirement.source }), stage: stageType,
      task: Type.Optional(Type.String({ pattern: validTask.source })), node: Type.Optional(Type.String()), parent: Type.Optional(Type.String()) }),
    async execute(_id, next, _signal, _update, ctx) {
      if ((next.stage === "execute" || next.stage === "verify") && !next.task) throw new Error("执行和验收阶段需要任务编号");
      await request(["board", next.requirement, ...(next.task ? [next.task] : []), "--json"], ctx.cwd);
      scope = { ...next };
      pi.appendEntry("ai-workflow-scope", { scope, cwd: ctx.cwd });
      await recordAgent(scope, ctx);
      await inputs(scope, ctx);
      if (initialSkill) { await observe(initialSkill, scope, ctx); initialSkill = undefined; }
      if (ctx.hasUI) ctx.ui.setStatus("ai-workflow", `${next.requirement}${next.task ? "/" + next.task : ""} · ${next.stage}`);
      return { content: [{ type: "text", text: `已设置节点：${next.requirement} · ${next.stage}${next.task ? " · " + next.task : ""}` }], details: { scope } };
    },
  });

  pi.registerTool({
    name: "ai_workflow_record", label: "AIWorkflow 节点输入输出",
    description: "Declare a node's core input, bounded delegation or output with retained evidence. Declarations are not observed agent calls.",
    parameters: Type.Object({ kind: Type.Union([Type.Literal("input"), Type.Literal("output"), Type.Literal("delegation"), Type.Literal("capability")]),
      name: Type.String(), summary: Type.String(), detail: Type.Optional(Type.Unknown()) }),
    async execute(_id, params, _signal, _update, ctx) {
      if (!scope) throw new Error("先设置AIWorkflow节点上下文");
      // Pass declared context over stdin too; do not expose potentially sensitive text in process arguments.
      const id = await request(["_observe-event", scope.requirement], ctx.cwd,
        { kind: params.kind, name: params.name, summary: params.summary, detail: params.detail ?? {},
          stage: scope.stage, task: scope.task, node: scope.node, parent: scope.parent, source: "declared" });
      return { content: [{ type: "text", text: "已保留节点记录（Agent声明，非独立调用证明）" }], details: { id: id.trim() } };
    },
  });

  pi.on("input", event => {
    pendingCommand = /^\/skill:([a-z0-9-]+)(?:\s|$)/.exec(event.text)?.[1];
    return { action: "continue" };
  });
  pi.on("before_agent_start", async (event, ctx) => {
    const command = pendingCommand;
    pendingCommand = undefined;
    if (event.messageType !== "user") return;
    pendingInput = { prompt: event.prompt, files: (event.systemPromptOptions?.contextFiles ?? [])
      .filter(file => typeof file.path === "string" && typeof file.content === "string")
      .map(file => ({ path: file.path, content: file.content })) };
    const expanded = /^<skill name="([^"]+)" location="([^"]+)">\n/.exec(event.prompt);
    if (command && expanded?.[1] === command) {
      const skill: Observed = { kind: "skill", name: command, source: "pi-command", summary: "用户调用Skill命令",
        detail: { path: expanded[2], content: event.prompt } };
      if (command === "ai-workflow") {
        scope = undefined;
        pi.appendEntry("ai-workflow-scope", { scope: null, cwd: ctx.cwd });
        if (ctx.hasUI) ctx.ui.setStatus("ai-workflow", undefined);
      }
      if (scope) await observe(skill, scope, ctx); else initialSkill = skill;
    }
    if (scope) await inputs(scope, ctx);
  });
  pi.on("agent_start", async (_event, ctx) => {
    run = randomUUID();
    if (scope) await recordAgent(scope, ctx);
  });
  pi.on("agent_end", async (event, ctx) => {
    if (!scope) return;
    const assistant = [...event.messages].reverse().find(message => message.role === "assistant");
    const content = assistant && Array.isArray(assistant.content)
      ? assistant.content.filter(block => block.type === "text").map(block => block.text).join("\n") : "";
    await observe({ kind: "output", name: "Agent本轮输出", source: "pi-event", parent: run,
      summary: "本轮对外答复，不含私有思考过程", detail: { content } }, scope, ctx);
  });

  pi.on("tool_execution_start", (event) => {
    if (!scope || event.toolName.startsWith("ai_workflow_")) return;
    calls.set(event.toolCallId, { scope: { ...scope }, input: structuredClone(event.args), observedInput: false,
      parent: event.parentToolCallId, run, owner: lifetime });
  });
  pi.on("tool_result", event => {
    const call = calls.get(event.toolCallId);
    if (call) { call.input = structuredClone(event.input); call.observedInput = true; }
  });
  pi.on("tool_execution_end", async (event, ctx) => {
    const call = calls.get(event.toolCallId);
    if (!call || call.owner.signal.aborted) return;
    const input = call.input as { path?: unknown; offset?: number; limit?: number } | undefined;
    const path = typeof input?.path === "string" ? input.path : undefined;
    let kind = "tool", name = event.toolName;
    if (!event.isError && event.toolName === "read" && path) {
      const canonical = await realpath(resolve(ctx.cwd, path.replace(/^@/, ""))).catch(() => undefined);
      if (call.owner.signal.aborted) return;
      if (canonical) {
        for (const command of pi.getCommands()) {
          if (command.source !== "skill") continue;
          if (await realpath(command.sourceInfo.path).catch(() => undefined) === canonical) {
            kind = "skill"; name = command.name.replace(/^skill:/, ""); break;
          }
        }
      }
      if (kind === "tool" && /(?:^|[\/\\])(?:AGENTS\.md|CLAUDE\.md)|[\/\\]rules[\/\\]|\.mdc$/.test(path)) {
        kind = "rule"; name = resolve(ctx.cwd, path.replace(/^@/, ""));
      }
    }
    if (call.owner.signal.aborted) return;
    await observe({ kind, name, source: kind === "skill" ? "pi-read" : "pi-event", node: event.toolCallId,
      parent: call.parent ?? call.run ?? call.scope.node, run: call.run,
      summary: `${event.toolName}${path ? " " + path : ""} · ${event.isError ? "失败" : "已观察"}`,
      detail: { tool: event.toolName, path, input: call.input, output: event.result, isError: event.isError,
        inputObservation: call.observedInput ? "tool_result最终输入" : "执行开始时输入；后续变更未完整观察",
        durationMs: event.durationMs, parentToolCallId: call.parent } }, call.scope, ctx);
    if (calls.get(event.toolCallId) === call) calls.delete(event.toolCallId);
  });

  async function view(title: string, text: string, ctx: ExtensionContext) {
    if (ctx.mode !== "tui") {
      if (ctx.hasUI) ctx.ui.notify(title + "\n" + text.slice(0, 2000) + (text.length > 2000 ? "\n[显示已截断；完整证据请用flow evidence读取]" : ""), "info");
      return;
    }
    await ctx.ui.custom<void>((tui, theme, keybindings, done) => {
      let offset = 0, cachedWidth = -1, lines: string[] = [];
      return {
        render(width: number) {
          if (cachedWidth !== width) { lines = new Text(text, 0, 0).render(width); cachedWidth = width; }
          const height = Math.max(1, tui.terminal.rows - 5);
          offset = Math.min(offset, Math.max(0, lines.length - height));
          return [truncateToWidth(theme.fg("accent", title), width), ...lines.slice(offset, offset + height),
            truncateToWidth(theme.fg("dim", "↑↓滚动 · Esc返回 · 只读证据"), width)];
        },
        handleInput(data: string) {
          if (keybindings.matches(data, "tui.select.cancel")) { done(); return; }
          if (keybindings.matches(data, "tui.select.down")) offset = Math.min(offset + 1, Math.max(0, lines.length - 1));
          else if (keybindings.matches(data, "tui.select.up")) offset = Math.max(0, offset - 1);
          else return;
          tui.requestRender();
        },
        invalidate() { cachedWidth = -1; },
      };
    });
  }

  async function browse(items: AuditItem[], title: string, requirement: string, ctx: ExtensionContext) {
    const options = items.map((item, index) => `${index + 1}. ${item.kind ?? ""} ${item.name}${item.node ? " · " + item.node : ""} [${item.source}]`);
    const choice = await ctx.ui.select(title, options);
    if (choice === undefined) return;
    const item = items[options.indexOf(choice)];
    if (!item) return;
    const data = item.evidence ? await request(["evidence", requirement, item.evidence, "--json"], ctx.cwd)
      : JSON.stringify({ ...item, limitation: item.limitation ?? "原文未观察到；不能补造历史上下文" }, null, 2);
    const header = { node: item.node ?? item.id, parent: item.parent, task: item.task,
      stage: item.stage, source: item.source, summary: item.summary, evidence: item.evidence,
      recorded_text_sha256: item.recorded_text_sha256 };
    await view(item.name, JSON.stringify(header, null, 2) + "\n\n原始证据：\n" + data, ctx);
  }

  pi.registerCommand("workflow", {
    description: "任务编排看板：输入、Skills/Rules、输出及逐项证据；不展开能力内部过程",
    handler: async (args, ctx) => {
      try {
        const words = args.trim() ? args.trim().split(/\s+/) : [];
        if (words.length > 2 || words[0] && !validRequirement.test(words[0]) || words[1] && !validTask.test(words[1]))
          throw new Error("用法：/workflow [需求ID] [T01]");
        if (!ctx.hasUI) {
          console.log(await request(["board", ...words], ctx.cwd)); return;
        }
        let requirement = words[0] ?? scope?.requirement, task = words[1];
        if (!requirement) {
          const all = JSON.parse(await request(["board", "--json"], ctx.cwd)) as { requirements: Board[] };
          const options = all.requirements.map(item => `${item.requirement} · ${item.title}`);
          const choice = await ctx.ui.select("AIWorkflow任务看板", options);
          if (choice === undefined) return;
          requirement = all.requirements[options.indexOf(choice)]?.requirement;
        }
        while (requirement) {
          const data = JSON.parse(await request(["board", requirement, ...(task ? [task] : []), "--json"], ctx.cwd)) as Board;
          if (!task) {
            const options = data.tasks.map(item => `${item.task} · ${item.title} · ${item.state}${item.after?.length ? " · 前置:" + item.after.join(",") : ""}${item.blocker ? " · " + item.blocker : ""}`);
            options.push("概览");
            const choice = await ctx.ui.select(`${data.title} · ${data.warnings.join("；")}`, options);
            if (choice === undefined) return;
            if (choice === "概览") await view(data.title, await request(["board", requirement], ctx.cwd), ctx);
            else task = data.tasks[options.indexOf(choice)]?.task;
            continue;
          }
          const options = ["概览", "输入", "能力 · Skills / Rules", "流程", "输出", "返回需求"];
          const links: { label: string; requirement: string; task?: string }[] = data.superiors.map(parent => ({ label: `返回上层 ${parent.requirement}/${parent.task}`, requirement: parent.requirement, task: parent.task }));
          for (const child of data.tasks[0]?.children ?? []) if (!child.warning)
            links.push({ label: `子需求 ${child.requirement}`, requirement: child.requirement, task: undefined });
          options.push(...links.map(link => link.label));
          const choice = await ctx.ui.select(`${data.requirement}/${task} · ${data.tasks[0]?.state}`, options);
          if (choice === undefined) return;
          if (choice === "概览") await view(`${requirement}/${task}`, await request(["board", requirement, task], ctx.cwd), ctx);
          else if (choice === "输入") await browse(data.inputs, "核心输入", requirement, ctx);
          else if (choice === "能力 · Skills / Rules") await browse([...data.skills, ...data.rules], "能力与规则（加载不等于正确遵循）", requirement, ctx);
          else if (choice === "流程") await browse(data.nodes, "真实节点与内部调用（按需深审）", requirement, ctx);
          else if (choice === "输出") await browse(data.outputs, "节点输出与验证", requirement, ctx);
          else if (choice === "返回需求") task = undefined;
          else { const link = links.find(item => item.label === choice); if (link) { requirement = link.requirement; task = link.task; } }
        }
      } catch (error) { if (ctx.hasUI) ctx.ui.notify(String(error), "error"); else console.error(String(error)); }
    },
  });
}
