import assert from "node:assert/strict";
import { resolve } from "node:path";
import extension from "../../Agents/pi/agency-work.ts";

const handlers = new Map<string, Function>();
const received: { message: any; options: any }[] = [];
const statuses: string[] = [];
let currentSession = "pi-work-test";
const ctx = { cwd: process.env.AGENCY_WORK_TEST_REPO!, hasUI: true,
    sessionManager: { getSessionId: () => currentSession },
    ui: { setStatus: (_key: string, text: string) => statuses.push(text) } };
extension({ on: (name: string, fn: Function) => handlers.set(name, fn),
    sendMessage: (message: any, options: any) => received.push({ message, options }) } as any);
const fire = async (event: string, value = {}) => {
    assert.ok(handlers.has(event));
    await handlers.get(event)!(value, ctx);
};
const tool = resolve(import.meta.dir, "../../Tools/agent-work");
function run(args: string[], token = "") {
    const result = Bun.spawnSync([tool, ...args, "--json"], { cwd: ctx.cwd,
        env: { ...process.env, AGENT_WORK_TOKEN: token } });
    assert.equal(result.exitCode, 0, new TextDecoder().decode(result.stderr));
    return JSON.parse(new TextDecoder().decode(result.stdout));
}
const owner = run(["start", "--task", "Pi owner", "--scope", "src"]);
await fire("session_start");
await fire("tool_result", { content: [{ type: "text", text: JSON.stringify(owner) }] });
const worker = run(["start", "--task", "Worker", "--no-claims"]);
const request = run(["request-claim", worker.id, "src", "--message", "Need the scope"], worker.task_token);
const deadline = Date.now() + 5000;
while (!received.some(item => item.message.content.includes(request.id)) && Date.now() < deadline) {
    await Bun.sleep(20);
}
assert.ok(received.some(item => item.message.content.includes(request.id)), "Watcher must wake an idle Pi session");
assert.ok(received.every(item => item.options.triggerTurn === true && item.options.deliverAs === "steer"));
assert.ok(received.every(item => item.message.customType === "agency-work"));
await fire("session_shutdown");
const count = received.length;
run(["broadcast", worker.id, "--message", "Old session must stay asleep"], worker.task_token);
await Bun.sleep(100);
assert.equal(received.length, count);
currentSession = "another-session";
await fire("session_start");
assert.equal(received.length, count, "New session must not receive the old task's inbox");
await fire("session_shutdown");
console.log("Pi claim inbox wake, steering and cleanup passed");
