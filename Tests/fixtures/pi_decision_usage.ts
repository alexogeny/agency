import assert from "node:assert/strict";
import { resolve } from "node:path";
import extension from "../../Agents/pi/agency-decisions.ts";

const handlers = new Map<string, Function>();
const statuses: string[] = [];
const context = {
    hasUI: true,
    sessionManager: { getSessionId: () => "pi-test-session" },
    ui: { setStatus: (_key: string, text: string) => statuses.push(text) },
};
extension({ on: (name: string, fn: Function) => handlers.set(name, fn) } as any);
const fire = async (name: string, event = {}) => {
    assert.ok(handlers.has(name), `Missing ${name} handler`);
    await handlers.get(name)!(event, context);
};
const receipt = () => {
    const generated = Bun.spawnSync(["python3", "-c",
        "import sys,json;sys.path.insert(0,sys.argv[1]);from agency_decision_usage import with_report;print(json.dumps(with_report({'decision':'relevant'})))",
        resolve(import.meta.dir, "../../Tools")]);
    assert.equal(generated.exitCode, 0);
    return new TextDecoder().decode(generated.stdout);
};
await fire("agent_start");
assert.equal(statuses.at(-1), "Jev: 0 decisions");
const value = receipt();
await fire("tool_result", { toolName: "bash", input: { command: "agency-decide classify" },
    content: [{ type: "text", text: value }] });
assert.equal(statuses.at(-1), "Jev: 1 decision");
await fire("tool_result", { toolName: "bash", input: { command: "agency-decide profiles" },
    content: [{ type: "text", text: "{}" }] });
assert.equal(statuses.at(-1), "Jev: 1 decision");
await fire("agent_start"); // Automatic retries are still part of this user run.
await fire("tool_result", { toolName: "bash", input: { command: "agency-decide classify" },
    content: [{ type: "text", text: value }] });
await fire("agent_settled");
assert.equal(statuses.at(-1), "Jev: 1 decision");
await fire("agent_start");
assert.equal(statuses.at(-1), "Jev: 0 decisions");
await fire("agent_settled");
await fire("session_start", { reason: "resume" });
assert.equal(statuses.at(-1), undefined);

await fire("agent_start");
const installedHelper = process.env.AGENCY_DECISION_USAGE_COMMAND;
process.env.AGENCY_DECISION_USAGE_COMMAND = "/missing/agency-decision-usage";
await fire("tool_result", { toolName: "bash", input: { command: "agency-decide classify" },
    content: [{ type: "text", text: receipt() }] });
process.env.AGENCY_DECISION_USAGE_COMMAND = installedHelper;
await fire("agent_settled");
assert.ok(statuses.at(-1)?.includes("incomplete"), "Lost tool events must remain visible at turn end");

const starting = fire("agent_start");
await fire("session_start", { reason: "new" });
await starting;
assert.equal(statuses.at(-1), undefined, "Old async results must not overwrite a new session's footer");
console.log("Pi usage lifecycle passed");
