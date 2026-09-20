import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const unavailable = "Jev: usage unavailable (counter could not read this event)";

async function usage(payload: object): Promise<string> {
    return new Promise((resolve) => {
        const child = spawn(process.env.AGENCY_DECISION_USAGE_COMMAND ||
            join(homedir(), ".local/bin/agency-decision-usage"), ["--client", "pi"],
            { stdio: ["pipe", "pipe", "ignore"] });
        let output = "";
        const timer = setTimeout(() => { child.kill(); resolve(unavailable); }, 3000);
        child.stdout.setEncoding("utf8");
        child.stdout.on("data", (chunk: string) => {
            output += chunk;
            if (output.length > 4096) child.kill();
        });
        child.on("error", () => { clearTimeout(timer); resolve(unavailable); });
        child.stdin.on("error", () => { clearTimeout(timer); resolve(unavailable); });
        child.on("close", (code) => {
            clearTimeout(timer);
            try {
                const result = JSON.parse(output);
                resolve(code === 0 && typeof result.systemMessage === "string"
                    ? result.systemMessage : unavailable);
            } catch { resolve(unavailable); }
        });
        child.stdin.end(JSON.stringify(payload));
    });
}

export default function agencyDecisions(pi: ExtensionAPI) {
    let turn: string | undefined;
    let session: string | undefined;
    let active = false;
    let incomplete = false;

    const show = (ctx: ExtensionContext, text: string, expectedTurn: string | undefined) => {
        if (turn !== expectedTurn || ctx.sessionManager.getSessionId() !== session) return;
        incomplete ||= text.includes("unavailable");
        if (incomplete && !text.includes("unavailable") && !text.includes("incomplete")) text += " · count incomplete";
        if (ctx.hasUI) ctx.ui.setStatus("agency-decisions", text);
    };

    pi.on("agent_start", async (_event, ctx) => {
        const current = ctx.sessionManager.getSessionId();
        // A retry or compaction can start another model run before agent_settled.
        if (active && current === session) return;
        session = current;
        turn = randomUUID();
        const currentTurn = turn;
        active = true;
        incomplete = false;
        const text = await usage({ hook_event_name: "UserPromptSubmit", session_id: session, turn_id: turn });
        show(ctx, text, currentTurn);
    });

    pi.on("tool_result", async (event, ctx) => {
        if (!active || ctx.sessionManager.getSessionId() !== session || event.toolName !== "bash") return;
        const currentTurn = turn;
        const command = typeof event.input?.command === "string" ? event.input.command : "";
        const hasReceipt = event.content.some(block => block.type === "text" && block.text.includes('"_agency_decisions"'));
        if (!hasReceipt && !(command.includes("agency-decide") && /\b(classify|classify-batch|evaluate)\b/.test(command))) return;
        const text = await usage({ hook_event_name: "PostToolUse", session_id: session, turn_id: turn,
            tool_name: "Bash", tool_input: { command }, tool_response: event.content });
        show(ctx, text, currentTurn);
    });

    pi.on("agent_settled", async (_event, ctx) => {
        if (!active) return;
        const currentTurn = turn;
        active = false;
        const text = await usage({ hook_event_name: "Stop", session_id: session, turn_id: turn });
        show(ctx, text, currentTurn);
    });

    pi.on("session_start", async (_event, ctx) => {
        active = false;
        incomplete = false;
        session = turn = undefined;
        if (ctx.hasUI) ctx.ui.setStatus("agency-decisions", undefined);
    });
}
