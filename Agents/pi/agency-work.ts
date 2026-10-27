import { spawn, type ChildProcess } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

type Batch = { event?: string; id?: string; context?: string; task_context?: string; registered?: boolean; systemMessage?: string };

export default function agencyWork(pi: ExtensionAPI) {
    let session: string | undefined;
    let watcher: ChildProcess | undefined;
    let generation = 0;
    const delivered = new Set<string>();

    const helper = (payload: object): Promise<Batch> => new Promise((resolve) => {
        const child = spawn(process.env.AGENCY_WORK_HOOK_COMMAND || join(homedir(), ".local/bin/agent-work-hook"),
            ["--client", "pi"], { stdio: ["pipe", "pipe", "ignore"] });
        let output = "";
        const timer = setTimeout(() => { child.kill(); resolve({ systemMessage: "Agency inbox helper timed out" }); }, 3000);
        child.stdout.setEncoding("utf8");
        child.stdout.on("data", (chunk: string) => {
            output += chunk;
            if (output.length > 1048576) child.kill();
        });
        child.on("error", () => { clearTimeout(timer); resolve({ systemMessage: "Agency inbox helper unavailable" }); });
        child.stdin.on("error", () => {});
        child.on("close", (code) => {
            clearTimeout(timer);
            try { resolve(code === 0 ? JSON.parse(output) : { systemMessage: "Agency inbox helper failed" }); }
            catch { resolve({ systemMessage: "Agency inbox helper returned invalid output" }); }
        });
        child.stdin.end(JSON.stringify(payload));
    });

    const show = (ctx: ExtensionContext, text: string) => {
        if (ctx.hasUI) ctx.ui.setStatus("agency-work", text);
    };

    const accept = (batch: Batch, ctx: ExtensionContext): boolean => {
        if (!batch.id || !batch.context) return false;
        if (!delivered.has(batch.id)) {
            pi.sendMessage({ customType: "agency-work", content: batch.context, display: true,
                details: { batchId: batch.id } }, { triggerTurn: true, deliverAs: "steer" });
            delivered.add(batch.id);
            if (delivered.size > 256) delivered.delete(delivered.values().next().value!);
        }
        show(ctx, "Agency inbox delivered");
        return true;
    };

    const watch = (ctx: ExtensionContext) => {
        if (watcher || !session) return;
        const expected = generation;
        const child = spawn(process.env.AGENCY_WORK_WATCH_COMMAND || join(homedir(), ".local/bin/agent-work-watch"),
            ["--client", "pi", "--session", session], { stdio: ["pipe", "pipe", "ignore"] });
        watcher = child;
        let buffered = "";
        child.stdout.setEncoding("utf8");
        child.stdout.on("data", (chunk: string) => {
            if (generation !== expected) return;
            buffered += chunk;
            if (buffered.length > 1048576) { child.kill(); show(ctx, "Agency inbox output exceeded limit"); return; }
            let end: number;
            while ((end = buffered.indexOf("\n")) >= 0) {
                const line = buffered.slice(0, end);
                buffered = buffered.slice(end + 1);
                try {
                    const batch = JSON.parse(line) as Batch;
                    if (batch.event === "ready") show(ctx, "Agency inbox connected");
                    if (batch.event === "messages" && accept(batch, ctx)) {
                        child.stdin.write(JSON.stringify({ delivered: batch.id }) + "\n");
                    }
                } catch { show(ctx, "Agency inbox delivery failed; messages will retry"); }
            }
        });
        child.stdin.on("error", () => {});
        child.on("error", () => {
            if (generation === expected) show(ctx, "Agency inbox watcher unavailable");
        });
        child.on("close", () => {
            if (watcher === child) watcher = undefined;
            if (generation === expected) show(ctx, "Agency inbox disconnected; reconnecting at next boundary");
        });
    };

    const boundary = async (ctx: ExtensionContext, event: string, response?: unknown, deferTasks = false) => {
        const expected = generation;
        const current = ctx.sessionManager.getSessionId();
        const batch = await helper({ session_id: current, cwd: ctx.cwd, hook_event_name: event, tool_response: response });
        if (expected !== generation || current !== session) return;
        if (batch.systemMessage) show(ctx, batch.systemMessage);
        if (batch.task_context && !deferTasks) {
            pi.sendMessage({ customType: "agency-tasks", content: batch.task_context, display: true },
                { triggerTurn: false, deliverAs: "steer" });
        }
        try {
            if (accept(batch, ctx)) await helper({ session_id: current, hook_event_name: "DeliveryReceipt", batch_id: batch.id });
        } catch { show(ctx, "Agency inbox delivery failed; messages will retry"); }
        if (batch.registered) watch(ctx);
        return batch;
    };

    pi.on("session_start", async (_event, ctx) => {
        generation++;
        watcher?.kill();
        watcher = undefined;
        delivered.clear();
        session = ctx.sessionManager.getSessionId();
        await boundary(ctx, "SessionStart", undefined, true);
    });
    pi.on("before_agent_start", async (_event, ctx) => {
        const batch = await boundary(ctx, "UserPromptSubmit", undefined, true);
        if (batch?.task_context) {
            return { message: { customType: "agency-tasks", content: batch.task_context, display: true } };
        }
    });
    pi.on("session_compact", async (_event, ctx) => { await boundary(ctx, "SessionStart"); });
    pi.on("agent_settled", async (_event, ctx) => { await boundary(ctx, "Stop"); });
    pi.on("tool_result", async (event, ctx) => {
        await boundary(ctx, "PostToolUse", event.content);
    });
    pi.on("session_shutdown", async () => {
        generation++;
        session = undefined;
        watcher?.kill();
        watcher = undefined;
        delivered.clear();
    });
}
