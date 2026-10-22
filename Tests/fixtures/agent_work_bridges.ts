import assert from "node:assert/strict";
import { resolve } from "node:path";
import { CodexDelivery, ClaudeDelivery } from "../../Tools/agent_work_bridge.ts";

const calls: { method: string; params: any }[] = [];
let state = "active";
let fail = false;
const rpc = async (method: string, params: any) => {
    calls.push({ method, params });
    if (method === "thread/read") return { thread: { status: { type: state } } };
    if (method === "thread/turns/list") return { data: [{ id: "turn-1", status: "inProgress" }] };
    if (fail) throw new Error("rejected");
    return {};
};
const codex = new CodexDelivery(rpc, "thread-1");
await codex.deliver("Active scope request");
assert.equal(calls.at(-1)!.method, "turn/steer");
assert.equal(calls.at(-1)!.params.expectedTurnId, "turn-1");
assert.equal(calls.at(-1)!.params.input[0].text, "Active scope request");
state = "idle";
await codex.deliver("Wake idle thread");
assert.equal(calls.at(-1)!.method, "turn/start");
assert.equal(calls.at(-1)!.params.toolOutput.output, "Wake idle thread");
assert.equal(calls.at(-1)!.params.model, undefined);
assert.equal(calls.at(-1)!.params.sandboxPolicy, undefined);
state = "notLoaded";
await codex.deliver("Resume registered thread");
assert.equal(calls.at(-2)!.method, "thread/resume");
fail = true;
await assert.rejects(codex.deliver("Never mark rejected input delivered"), /rejected/);

const sent: any[] = [];
const claude = new ClaudeDelivery((message) => sent.push(message), "claude-session");
let accepted = false;
const pending = claude.deliver("Owner request").then(() => { accepted = true; });
await Promise.resolve();
assert.equal(accepted, false);
claude.receive({ ...sent[0], session_id: "foreign-session" });
await Promise.resolve();
assert.equal(accepted, false);
claude.receive(sent[0]);
await pending;
assert.equal(accepted, true);
assert.equal(sent[0].message.content, "Owner request");
const rejected = claude.deliver("Transport closes");
claude.close();
await assert.rejects(rejected, /closed/);
console.log("Controlled Codex steering, idle wake and Claude receipts passed");

if (process.env.AGENCY_WORK_TEST_REPO) {
    const repo = process.env.AGENCY_WORK_TEST_REPO;
    const tool = resolve(import.meta.dir, "../../Tools/agent-work");
    const run = (args: string[], token = "") => {
        const result = Bun.spawnSync([tool, ...args, "--json"], { cwd: repo,
            env: { ...process.env, AGENT_WORK_TOKEN: token } });
        assert.equal(result.exitCode, 0, new TextDecoder().decode(result.stderr));
        return JSON.parse(new TextDecoder().decode(result.stdout));
    };
    const waitUntil = async (condition: () => boolean) => {
        const deadline = Date.now() + 5000;
        while (!condition() && Date.now() < deadline) await Bun.sleep(20);
        assert.ok(condition(), "Controlled bridge timed out");
    };
    const networkCalls: any[] = [];
    let active = true;
    const server = Bun.serve({ hostname: "127.0.0.1", port: 0,
        fetch(request, server) { return server.upgrade(request) ? undefined : new Response("upgrade", { status: 400 }); },
        websocket: { message(socket, raw) {
            const message = JSON.parse(String(raw));
            networkCalls.push(message);
            if (!message.id) return;
            const result = message.method === "thread/read" ? { thread: { status: { type: active ? "active" : "idle" } } }
                : message.method === "thread/turns/list" ? { data: [{ id: "active-turn", status: "inProgress" }] } : {};
            socket.send(JSON.stringify({ id: message.id, result }));
        } } });
    const owner = run(["start", "--task", "Controlled owner", "--scope", "src", "--client", "codex", "--session", "controlled-thread"]);
    const bridge = Bun.spawn([resolve(import.meta.dir, "../../Tools/agent-work-bridge"), "--client", "codex",
        "--session", "controlled-thread", "--url", `ws://127.0.0.1:${server.port}`],
        { cwd: repo, stdin: "pipe", stdout: "pipe", stderr: "pipe", env: process.env });
    try {
        await waitUntil(() => networkCalls.some(item => item.method === "initialized"));
        const worker = run(["start", "--task", "Controlled requester", "--no-claims"]);
        const request = run(["request-claim", worker.id, "src", "--message", "Controlled request"], worker.task_token);
        await waitUntil(() => networkCalls.some(item => item.method === "turn/steer" && item.params.input[0].text.includes(request.id)));
        await waitUntil(() => run(["inbox", owner.id]).some((item: any) => item.kind === "claim-request" && item.state === "delivered"));
        active = false;
        run(["broadcast", worker.id, "--message", "Wake the controlled idle thread"], worker.task_token);
        await waitUntil(() => networkCalls.some(item => item.method === "turn/start" && item.params.toolOutput.output.includes("Wake the controlled idle thread")));
    } finally {
        bridge.kill();
        const shutdownTimer = setTimeout(() => bridge.kill("SIGKILL"), 2000);
        await bridge.exited;
        clearTimeout(shutdownTimer);
        server.stop(true);
    }
    console.log("Codex WebSocket bridge and durable receipts passed");
}
