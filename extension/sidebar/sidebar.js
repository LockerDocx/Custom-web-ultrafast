const $ = (id) => document.getElementById(id);
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

let state = null;

function setConnection(connected) {
  $("connection").classList.toggle("on", connected);
  $("connection").querySelector("em").textContent = connected ? "host online" : "offline";
  $("run").disabled = !connected;
}

function render() {
  if (!state) return;
  const live = state.page && !["done", "blocked"].includes(state.status);
  $("stop").hidden = !live;
  $("live").hidden = !state.page;
  const labels = {
    idle: state.error ? "stopped — see the error below" : "idle",
    ready: "page observed · ready",
    predicted: "choice ready",
    done: "done ✓",
    blocked: "blocked",
  };
  $("status").textContent = labels[state.status] || state.status || "";
  $("step-count").textContent =
    state.history && state.history.length
      ? `${state.history.length} actions · ${(state.elapsed_ms / 1000).toFixed(1)} s`
      : "";
  if (state.page) {
    if (state.page.screenshot) $("screenshot").src = `data:image/jpeg;base64,${state.page.screenshot}`;
    $("screenshot").alt = state.page.title || state.page.url;
  }
  const plan = state.plan || [];
  $("plan").innerHTML = plan.length
    ? plan
        .map((step, i) => {
          const cls = i < state.plan_index ? "done" : i === state.plan_index ? "current" : "";
          return `<li class="${cls}"><span>${i < state.plan_index ? "✓" : i + 1}</span>${escape(step)}</li>`;
        })
        .join("")
    : '<li class="done"><span></span>Single-goal run</li>';
  const history = state.history || [];
  $("history").innerHTML = history.length
    ? history
        .slice(-12)
        .map(
          (h) =>
            `<div><span class="number">${String(h.step).padStart(2, "0")}</span><span>${escape(h.action)}` +
            (h.text ? ` <b>“${escape(h.text)}”</b>` : "") +
            `</span><span class="time">${h.latency_ms} ms</span></div>`,
        )
        .join("")
    : '<div><span class="number">—</span><span>No actions yet</span></div>';
  $("models").textContent = [state.planner && `planner · ${state.planner}`, state.policy && `policy · ${state.policy}`]
    .filter(Boolean)
    .join("   ·   ") || "no models configured";
  renderProviders(state.providers);
  renderError(state.error);
}

function renderProviders(providers) {
  const box = $("providers");
  if (!providers || !Object.keys(providers).length) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const names = { planner: "Planner", policy: "Executor", text: "Text writer" };
  box.innerHTML = Object.values(providers)
    .map((p) => {
      const dot = p.ok ? "🟢" : "🔴";
      const extra = p.ok
        ? `${p.latency_ms != null ? ` ${p.latency_ms} ms` : ""}`
        : `<small>${escape(p.detail || "not configured")}</small>`;
      return `<div class="provider ${p.ok ? "ok" : "bad"}" title="${escape(p.detail || "")}">${dot} ${names[p.role] || p.role} · <b>${escape(p.model || "?")}</b>${extra}</div>`;
    })
    .join("");
}

function renderError(error) {
  const box = $("error");
  if (error) {
    box.textContent = error;
    box.hidden = false;
  }
}

browser.runtime.onMessage.addListener((message) => {
  if (message.type === "status") setConnection(message.connected);
  if (message.type === "state") {
    state = message.state;
    render();
  }
  if (message.type === "error") {
    // The next state broadcast carries the same error persistently; show it now.
    $("error").textContent = message.message;
    $("error").hidden = false;
  }
  if (message.type === "checking") {
    $("providers").hidden = false;
    $("providers").innerHTML = '<div class="provider">⏳ Checking the model connections…</div>';
  }
});

$("run").addEventListener("click", async () => {
  const goal = $("goal").value.trim();
  if (!goal) return;
  $("error").hidden = true;
  $("error").textContent = "";
  if (state) state.error = null;
  const reply = await browser.runtime.sendMessage({ cmd: "run", goal });
  if (reply && reply.error) {
    $("error").textContent = reply.error;
    $("error").hidden = false;
  }
});

$("check").addEventListener("click", async () => {
  $("error").hidden = true;
  const reply = await browser.runtime.sendMessage({ cmd: "check" });
  if (reply && reply.error) {
    $("error").textContent = reply.error;
    $("error").hidden = false;
  }
});

$("stop").addEventListener("click", () => {
  browser.runtime.sendMessage({ cmd: "stop" });
});

(async () => {
  const status = await browser.runtime.sendMessage({ cmd: "status" });
  setConnection(status.connected);
  if (status.state) {
    state = status.state;
    render();
  }
})();
