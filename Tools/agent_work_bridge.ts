import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

type Rpc = (method: string, params: Record<string, unknown>) => Promise<any>;

export class CodexDelivery {
    constructor(private rpc: Rpc, private session: string) {}

    async deliver(context: string): Promise<void> {
        const result = await this.rpc("thread/read", { threadId: this.session });
        const state = result.thread.status.type;
        if (state === "notLoaded") await this.rpc("thread/resume", { threadId: this.session });
        if (state === "systemError") throw new Error("Codex thread reports a system error");
        if (state === "active") {
            const turns = await this.rpc("thread/turns/list", { threadId: this.session, limit: 1,
                sortDirection: "desc", itemsView: "notLoaded" });
            const active = turns.data.find((turn: any) => turn.status === "inProgress");
            if (!active) throw new Error("Codex active turn changed; retry after reconciliation");
            await this.rpc("turn/steer", { threadId: this.session, expectedTurnId: active.id,
                input: [{ type: "text", text: context }] });
        } else {
            await this.rpc("turn/start", { threadId: this.session, input: [],
                toolOutput: { name: "agency_coordination", output: context } });
        }
    }
}

export class ClaudeDelivery {
    private pending = new Map<string, { resolve: () => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
    constructor(private write: (value: object) => void, private session: string) {}

    deliver(context: string): Promise<void> {
        const uuid = randomUUID();
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => { this.pending.delete(uuid); reject(new Error("Claude did not acknowledge input")); }, 12000);
            this.pending.set(uuid, { resolve, reject, timer });
            try {
                this.write({ type: "user", session_id: this.session, uuid, parent_tool_use_id: null,
                    message: { role: "user", content: context } });
            } catch (error) {
                clearTimeout(timer);
                this.pending.delete(uuid);
                reject(error);
            }
        });
    }

    receive(event: any): void {
        if (event.type !== "user" || event.session_id !== this.session || !this.pending.has(event.uuid)) return;
        const item = this.pending.get(event.uuid)!;
        clearTimeout(item.timer);
        this.pending.delete(event.uuid);
        item.resolve();
    }

    close(): void {
        for (const item of this.pending.values()) {
            clearTimeout(item.timer);
            item.reject(new Error("Claude transport closed before acknowledging input"));
        }
        this.pending.clear();
    }
}

async function websocketRpc(url: string, tokenFile?: string): Promise<{ rpc: Rpc; close: () => void; send: (value: unknown) => void }> {
    const location = new URL(url);
    if (location.protocol !== "ws:" || !["127.0.0.1", "localhost", "[::1]"].includes(location.hostname)) {
        throw new Error("Codex bridge requires an explicit loopback ws:// app-server endpoint");
    }
    const headers: Record<string, string> = {};
    if (tokenFile) {
        const token = readFileSync(tokenFile, "utf8").trim();
        if (!token || token.length > 4096 || /[\r\n]/.test(token)) throw new Error("Invalid app-server token file");
        headers.Authorization = `Bearer ${token}`;
    }
    const channel = new WebSocket(url, { headers });
    const pending = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
    let sequence = 0;
    const opened = new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => { channel.close(); reject(new Error("App-server connection timed out")); }, 10000);
        channel.addEventListener("open", () => { clearTimeout(timer); resolve(); }, { once: true });
        channel.addEventListener("error", () => { clearTimeout(timer); reject(new Error("App-server connection failed")); }, { once: true });
    });
    channel.addEventListener("message", (event) => {
        try {
            const message = JSON.parse(String(event.data));
            if (message.method) {
                if (message.id !== undefined) console.log(JSON.stringify({ event: "app-server-request", request: message }));
                return;
            }
            const request = pending.get(message.id);
            if (!request) return;
            clearTimeout(request.timer);
            pending.delete(message.id);
            if (message.error) request.reject(new Error(`App-server rejected ${message.id}: ${message.error.message}`));
            else request.resolve(message.result);
        } catch { console.error("Agency bridge: invalid app-server frame"); }
    });
    channel.addEventListener("close", () => {
        for (const item of pending.values()) { clearTimeout(item.timer); item.reject(new Error("App-server disconnected")); }
        pending.clear();
    });
    await opened;
    const rpc: Rpc = (method, params) => new Promise((resolve, reject) => {
        const id = ++sequence;
        const timer = setTimeout(() => { pending.delete(id); reject(new Error(`App-server ${method} timed out`)); }, 12000);
        pending.set(id, { resolve, reject, timer });
        try { channel.send(JSON.stringify({ id, method, params })); }
        catch (error) { clearTimeout(timer); pending.delete(id); reject(error); }
    });
    await rpc("initialize", { clientInfo: { name: "agency_claims", title: "Agency claim register", version: "1" } });
    channel.send(JSON.stringify({ method: "initialized", params: {} }));
    return { rpc, close: () => channel.close(), send: (value) => channel.send(JSON.stringify(value)) };
}

async function main(): Promise<void> {
    const values = new Map<string, string>();
    const extras: string[] = [];
    const argv = Bun.argv.slice(2);
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === "--") { extras.push(...argv.slice(i + 1)); break; }
        if (argv[i] === "--help") {
            console.log("agent-work-bridge --client codex --session THREAD --url ws://127.0.0.1:PORT [--token-file PATH]\n" +
                "agent-work-bridge --client claude --session UUID [--claude-command PATH] [--resume yes] [-- CLAUDE_OPTIONS...]\n" +
                "Claude mode launches a controlled worker; it cannot attach to an arbitrary TUI. Stdin/stdout carry client JSONL.");
            return;
        }
        if (!["--client", "--session", "--url", "--token-file", "--claude-command", "--resume"].includes(argv[i]) || !argv[i + 1]) {
            throw new Error(`Unsupported or incomplete option: ${argv[i]}`);
        }
        values.set(argv[i], argv[++i]);
    }
    const client = values.get("--client");
    const session = values.get("--session");
    if (!session || !["codex", "claude"].includes(client || "")) throw new Error("Specify --client codex|claude and --session ID");
    let deliver: (context: string) => Promise<void>;
    let close: () => void;
    let forward: (value: any) => void;
    if (client === "codex") {
        if (!values.has("--url")) throw new Error("Codex bridge requires --url for the controlled app-server");
        const transport = await websocketRpc(values.get("--url")!, values.get("--token-file"));
        const adapter = new CodexDelivery(transport.rpc, session);
        deliver = (context) => adapter.deliver(context);
        close = transport.close;
        forward = transport.send;
    } else {
        if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(session)) throw new Error("Claude session ID must be a UUID");
        const child = spawn(values.get("--claude-command") || "claude", ["-p", "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose", "--replay-user-messages",
            values.get("--resume") === "yes" ? "--resume" : "--session-id", session, ...extras],
            { stdio: ["pipe", "pipe", "inherit"] });
        const adapter = new ClaudeDelivery((value) => child.stdin.write(JSON.stringify(value) + "\n"), session);
        createInterface({ input: child.stdout }).on("line", (line) => {
            try { adapter.receive(JSON.parse(line)); }
            catch { console.error("Agency bridge: invalid Claude event"); }
            console.log(line);
        });
        child.on("error", (error) => { console.error(`Agency bridge: ${error.message}`); adapter.close(); });
        child.on("close", () => { adapter.close(); process.emit("SIGTERM"); });
        child.stdin.on("error", () => adapter.close());
        deliver = (context) => adapter.deliver(context);
        close = () => { adapter.close(); child.kill(); };
        forward = (value) => child.stdin.write(JSON.stringify(value) + "\n");
    }
    const watcher = spawn(join(dirname(fileURLToPath(import.meta.url)), "agent-work-watch"),
        ["--client", client!, "--session", session], { stdio: ["pipe", "pipe", "inherit"] });
    let stopped = false;
    const shutdown = () => { if (!stopped) { stopped = true; watcher.kill(); close(); } };
    process.on("SIGTERM", shutdown);
    process.on("SIGINT", shutdown);
    const input = createInterface({ input: process.stdin });
    input.on("line", (line) => {
        try { forward(JSON.parse(line)); }
        catch { console.error("Agency bridge: stdin expects client JSONL"); }
    });
    input.on("close", shutdown);
    let queue = Promise.resolve();
    createInterface({ input: watcher.stdout }).on("line", (line) => {
        queue = queue.then(async () => {
            const batch = JSON.parse(line);
            if (batch.event !== "messages" || stopped) return;
            await deliver(batch.context);
            watcher.stdin.write(JSON.stringify({ delivered: batch.id }) + "\n");
        }).catch((error) => console.error(`Agency bridge: ${error.message}; delivery remains retryable`));
    });
    watcher.stdin.on("error", shutdown);
    watcher.on("error", shutdown);
    watcher.on("close", () => { input.close(); shutdown(); });
}

if (import.meta.main) {
    main().catch((error) => { console.error(`Agency bridge: ${error.message}`); process.exitCode = 1; });
}
