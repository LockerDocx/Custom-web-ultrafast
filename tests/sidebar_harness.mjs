/**
 * Headless harness for the agent sidebar.
 *
 * The panel is the only surface a user has, and its logic (progress, the
 * conversation view, the log, the readiness verdict) had no test at all: the
 * Python suite can only check that element ids exist. This runs sidebar.js
 * against a stub DOM, feeds it the same messages the host broadcasts during a
 * real run, and reports what the panel rendered.
 *
 * Usage: node tests/sidebar_harness.mjs extension/sidebar/sidebar.js
 *        (prints one JSON object on stdout; the pytest wrapper asserts on it)
 */

import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(process.argv[2], "utf8");

/* ── a DOM stub that records what the panel does with it ────────────────── */

const elements = new Map();
const listeners = new Map(); // "id:type" -> handler

function makeElement(id) {
  const classes = new Set();
  return {
    id,
    hidden: false,
    textContent: "",
    innerHTML: "",
    value: "",
    disabled: false,
    dataset: {},
    style: {},
    scrollTop: 0,
    scrollHeight: 100,
    clientHeight: 100,
    classList: {
      toggle: (name, on) => (on === undefined ? classes.has(name) : on ? classes.add(name) : classes.delete(name)),
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      get: () => [...classes],
    },
    addEventListener: (type, handler) => listeners.set(`${id}:${type}`, handler),
    // the panel reaches into children (e.g. the <em> inside #connection): give it
    // a stub that records whatever is written, instead of null
    querySelector: (selector) => {
      const key = `${id} ${selector}`;
      if (!elements.has(key)) elements.set(key, makeElement(key));
      return elements.get(key);
    },
    querySelectorAll: () => [],
    setAttribute: (name, value) => {
      if (name === "aria-valuenow") listeners.get("__aria__") || elements.get(id); // noop
      const store = elements.get(id);
      if (store) store.dataset[`attr_${name}`] = String(value);
    },
    getAttribute: () => null,
    closest: () => null,
  };
}

const messageListeners = [];

const sandbox = {
  console: { log: () => {}, error: () => {}, warn: () => {} },
  setTimeout,
  clearTimeout,
  Date,
  Math,
  JSON,
  String,
  Number,
  Object,
  Array,
  RegExp,
  Promise,
  document: {
    getElementById: (id) => {
      if (!elements.has(id)) elements.set(id, makeElement(id));
      return elements.get(id);
    },
    // the two activity tabs are real enough to be clicked
    querySelectorAll: (selector) => {
      if (selector !== "#activity .tab") return [];
      return ["chat", "log"].map((view) => {
        const tab = makeElement(`tab-${view}`);
        tab.dataset = { view };
        tab.addEventListener = (type, handler) => listeners.set(`tab-${view}:${type}`, handler);
        return tab;
      });
    },
    addEventListener: () => {},
  },
  browser: {
    runtime: {
      onMessage: { addListener: (handler) => messageListeners.push(handler) },
      sendMessage: async () => ({ connected: false }),
    },
    tabs: { create: () => {} },
  },
};
sandbox.window = sandbox;

vm.createContext(sandbox);
vm.runInContext(source, sandbox);

const el = (id) => {
  if (!elements.has(id)) elements.set(id, makeElement(id));
  return elements.get(id);
};
const send = async (message) => {
  for (const handler of messageListeners) await handler(message);
  await new Promise((resolve) => setImmediate(resolve));
};
const click = async (id) => {
  const handler = listeners.get(`${id}:click`);
  if (!handler) throw new Error(`no click handler on #${id}`);
  await handler();
  await new Promise((resolve) => setImmediate(resolve));
};

/* ── a run, as the host broadcasts it ───────────────────────────────────── */

const provider = (role, model, ok = true) => ({ role, model, ok, latency_ms: ok ? 120 : null, detail: ok ? "" : "No API key" });
const base = {
  status: "idle",
  mode: "browser",
  trace: "trace-1",
  tokens: 0,
  providers: {
    planner: provider("planner", "z-ai/glm-5.3"),
    policy: provider("policy", "openai/gpt-oss-20b"),
    text: provider("text", "openai/gpt-oss-20b"),
  },
  setup: { configured: true, keys: {}, free: [], selection: {} },
  sandbox: {},
  browserMode: "live",
  step_budget: 25,
};

const report = {};

// 1. before anything happens the panel has nothing to show
report.emptyChat = el("chat").innerHTML === "";

// 2. a mission is launched: the conversation opens with what the user asked
el("goal").value = "Book the cheapest direct flight";
await click("run");
report.chatAfterRun = el("chat").innerHTML;
report.viewAfterRun = { chatHidden: el("chat").hidden, logHidden: el("log").hidden };

// 3. orchestrated run in progress: a step arrives, the model is streaming, time passes
await send({ type: "state", state: { ...base, mode: "orchestrated", status: "running", elapsed_ms: 4200, log: [] } });
await send({ type: "delta", text: "I will search for flights first" });
await send({
  type: "state",
  state: {
    ...base,
    mode: "orchestrated",
    status: "running",
    elapsed_ms: 7300,
    tokens: 3120,
    log: [{ step: 1, tool: "web_search", args: { query: "flights Zurich London" }, result: "12 results", error: null, final: null }],
  },
});
report.chatMidRun = el("chat").innerHTML;
report.metaMidRun = el("activity-meta").textContent;
report.statusMidRun = el("activity-status").textContent;
report.barMidRun = { width: el("progress-fill").style.width, indeterminate: el("progress").classList.contains("indeterminate") };
report.noteMidRun = el("progress-note").textContent;

// 4. it finishes with an answer
await send({
  type: "state",
  state: {
    ...base,
    mode: "orchestrated",
    status: "done",
    elapsed_ms: 18500,
    tokens: 9100,
    log: [
      { step: 1, tool: "web_search", args: { query: "flights" }, result: "12 results", error: null, final: null },
      { step: 2, final: "The cheapest direct flight is 84 EUR at 07:15.", error: null, tool: null },
    ],
  },
});
report.chatDone = el("chat").innerHTML;
report.barDone = { width: el("progress-fill").style.width, label: el("activity-status").textContent, done: el("progress").classList.contains("done") };

// 5. the raw log keeps every event, with its level (view switch included)
await send({ type: "notice", message: "Saved GROQ_API_KEY to .env. Testing it now…" });
await click("activity-clear");
report.afterClear = { hidden: el("activity").hidden };

// 6. browser mode: a plan makes the bar determinate, and each step is announced
await send({
  type: "state",
  state: { ...base, status: "running", plan: ["Open the airline site", "Search flights", "Read the price"], plan_index: 1 },
});
report.barPlan = { width: el("progress-fill").style.width, label: el("activity-status").textContent, indeterminate: el("progress").classList.contains("indeterminate") };
report.chatPlan = el("chat").innerHTML;

// 7. the readiness verdict
report.readyOk = { text: el("ready-text").innerHTML, dot: el("ready-dot").textContent, bad: el("ready").classList.contains("bad") };
await send({
  type: "state",
  state: { ...base, providers: { planner: provider("planner", "z-ai/glm-5.3"), policy: provider("policy", "?", false), text: provider("text", "?", false) } },
});
report.readyBad = { text: el("ready-text").innerHTML, dot: el("ready-dot").textContent, bad: el("ready").classList.contains("bad") };

// 8. an error is never silent
await send({ type: "error", message: "Groq rejected the key (401)" });
report.chatError = el("chat").innerHTML;

await click("tab-log");
report.logView = { chatHidden: el("chat").hidden, logHidden: el("log").hidden, html: el("log").innerHTML };
await click("tab-chat");
report.chatView = { chatHidden: el("chat").hidden, logHidden: el("log").hidden };

process.stdout.write(JSON.stringify(report));
