import { type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { realpath } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Type } from "typebox";

type Stage = "clarify" | "plan" | "execute" | "verify";
type Scope = { requirement: string; stage: Stage; task?: string };
type Observed = { name: string; source: "pi-read" | "pi-command"; path: string };

const workflow = fileURLToPath(new URL("../workflow.py", import.meta.url));

export default function (pi: ExtensionAPI) {
  let scope: Scope | undefined;
  let initialEntry: Observed | undefined;
  let pendingCommand: string | undefined;

  pi.on("session_start", () => {
    scope = undefined;
    initialEntry = undefined;
    pendingCommand = undefined;
  });

  async function record(event: Observed, current: Scope, cwd: string) {
    const args = [workflow, "_observe-skill", current.requirement, event.name,
      "--stage", current.stage, "--source", event.source, "--evidence", event.path];
    if (current.task) args.push("--task", current.task);
    const result = await pi.exec("python3", args, { cwd, timeout: 5000 });
    if (result.code !== 0) throw new Error(result.stderr.trim() || "无法记录 Skill 观察");
  }

  async function observe(event: Observed, ctx: {cwd: string; ui: {notify: (message: string, type: "warning") => void}}) {
    if (!scope) {
      if (event.name === "ai-workflow") initialEntry = event;
      return;
    }
    try {
      await record(event, scope, ctx.cwd);
    } catch (error) {
      ctx.ui.notify(String(error), "warning");
    }
  }

  pi.registerTool({
    name: "ai_workflow_audit_context",
    label: "AIWorkflow 审计上下文",
    description: "Associate subsequently observed Skill loads with an initialized AIWorkflow requirement and stage.",
    parameters: Type.Object({
      requirement: Type.String({ pattern: "^[a-zA-Z0-9][a-zA-Z0-9_-]*$" }),
      stage: Type.Union([Type.Literal("clarify"), Type.Literal("plan"), Type.Literal("execute"), Type.Literal("verify")]),
      task: Type.Optional(Type.String({ pattern: "^T[0-9]{2,}$" })),
    }),
    async execute(_id, next, _signal, _update, ctx) {
      if ((next.stage === "execute" || next.stage === "verify") && !next.task) {
        throw new Error("执行和验收阶段需要任务编号");
      }
      if (initialEntry) {
        await record(initialEntry, { requirement: next.requirement, stage: "clarify" }, ctx.cwd);
        initialEntry = undefined;
      }
      scope = next;
      return { content: [{ type: "text", text: `已设置 AIWorkflow 审计上下文：${next.requirement} · ${next.stage}${next.task ? ` · ${next.task}` : ""}` }], details: {} };
    },
  });

  pi.on("input", (event) => {
    pendingCommand = /^\/skill:([a-z0-9-]+)(?:\s|$)/.exec(event.text)?.[1];
    return { action: "continue" };
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const name = pendingCommand;
    pendingCommand = undefined;
    if (!name || event.messageType !== "user") return;
    const expanded = /^<skill name="([^"]+)" location="([^"]+)">\n/.exec(event.prompt);
    if (expanded?.[1] === name) {
      if (name === "ai-workflow") scope = undefined;
      await observe({ name, path: expanded[2], source: "pi-command" }, ctx);
    }
  });

  pi.on("tool_result", async (event, ctx) => {
    if (!scope || event.toolName !== "read" || event.isError || typeof event.input.path !== "string") return;
    const path = await realpath(resolve(ctx.cwd, event.input.path)).catch(() => undefined);
    if (!path) return;
    for (const command of pi.getCommands()) {
      if (command.source !== "skill") continue;
      const registered = await realpath(command.sourceInfo.path).catch(() => undefined);
      if (registered === path) {
        await observe({ name: command.name.slice("skill:".length), path, source: "pi-read" }, ctx);
        break;
      }
    }
  });
}
