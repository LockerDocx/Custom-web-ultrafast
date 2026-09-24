const $ = (id) => document.getElementById(id);
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
const trunc = (text, n) => (String(text ?? "").length > n ? `${String(text).slice(0, n)}…` : String(text ?? ""));

let state = null;
let registry = null; // model catalogue from the host ("models" messages)
let approvalId = null;
let modelsSignature = "";
let permissionsSignature = "";

function setConnection(connected) {
  $("connection").classList.toggle("on", connected);
  $("connection").querySelector("em").textContent = connected ? "host online" : "offline";
  $("run").disabled = !connected;
}

/* ── main render ─────────────────────────────────────────────────── */

function render() {
  if (!state) return;
  const mode = state.mode || "browser";
  const live = mode === "orchestrated" ? state.browser || null : state;
  const running = !["done", "blocked", "idle", "stopped", "error"].includes(state.status);
  $("stop").hidden = !running;
  $("live").hidden = !(live && live.page);
  $("task").hidden = mode !== "orchestrated";
  if (mode === "orchestrated") renderTask(state);
  if (live && live.page) renderLive(live);
  const footer = [state.planner && `planner · ${state.planner}`, state.policy && `policy · ${state.policy}`]
    .filter(Boolean)
    .join("   ·   ") || "no models configured";
  $("models").textContent = footer;
  renderModelsPanel();
  renderTarget(state);
  renderPermissions(state.permissions);
  renderProviders(state.providers);
  renderError(state.error);
}

function renderLive(live) {
  const labels = {
    idle: "idle",
    ready: "page observed · ready",
    predicted: "choice ready",
    done: "done ✓",
    blocked: "blocked",
  };
  $("status").textContent = labels[live.status] || live.status || "";
  $("step-count").textContent = [
    live.history && live.history.length ? `${live.history.length} actions` : "",
    live.elapsed_ms ? `${(live.elapsed_ms / 1000).toFixed(1)} s` : "",
    state.tokens ? `${state.tokens >= 1000 ? (state.tokens / 1000).toFixed(1) + "k" : state.tokens} tokens` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  if (live.page.screenshot) $("screenshot").src = `data:image/jpeg;base64,${live.page.screenshot}`;
  $("screenshot").alt = live.page.title || live.page.url;
  const plan = live.plan || [];
  $("plan").innerHTML = plan.length
    ? plan
        .map((step, i) => {
          const cls = i < live.plan_index ? "done" : i === live.plan_index ? "current" : "";
          return `<li class="${cls}"><span>${i < live.plan_index ? "✓" : i + 1}</span>${escape(step)}</li>`;
        })
        .join("")
    : '<li class="done"><span></span>Single-goal run</li>';
  const history = live.history || [];
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
}

function renderTask(task) {
  const labels = { running: "working…", done: "done ✓", stopped: "stopped", error: "failed", idle: "idle" };
  $("task-status").textContent = labels[task.status] || task.status || "";
  const usage = task.usage || {};
  const tokens = [usage.input_tokens || usage.prompt_tokens, usage.output_tokens || usage.completion_tokens]
    .filter(Boolean)
    .reduce((a, b) => a + b, 0);
  $("task-meta").textContent = [
    (task.log || []).length ? `${task.log.length} steps` : "",
    task.latency_ms ? `${(task.latency_ms / 1000).toFixed(1)} s` : "",
    tokens ? `${tokens} tokens` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  $("thinking").hidden = true; // a step arrived: the live model output is now a step entry
  const skills = task.skills || [];
  $("task-skills").innerHTML = skills.length
    ? skills.map((s) => `<span class="chip" title="Skill guiding this mission">🧩 ${escape(s)}</span>`).join("")
    : "";
  const log = task.log || [];
  $("task-log").innerHTML = log.length
    ? log
        .map((s) => {
          const head = s.tool
            ? `🔧 <code>${escape(s.tool)}(${escape(compactArgs(s.args))})</code>`
            : s.final
              ? "🏁 final answer"
              : `⚠️ ${escape(s.error || "step")}`;
          const body = [
            s.error && !s.final ? `<span class="err">${escape(s.error)}</span>` : "",
            s.result ? `<span class="res">${escape(trunc(s.result, 240))}</span>` : "",
          ]
            .filter(Boolean)
            .join("");
          return `<div class="task-step${s.error && !s.final ? " bad" : ""}"><div class="head"><span class="number">${String(s.step).padStart(2, "0")}</span><span>${head}</span></div>${body}</div>`;
        })
        .join("")
    : '<div class="task-step"><div class="head"><span class="number">—</span><span>No steps yet</span></div></div>';
  $("task-log").scrollTop = $("task-log").scrollHeight;
  if (task.final) {
    $("task-final").textContent = task.final;
    $("task-final").hidden = false;
  } else {
    $("task-final").hidden = true;
  }
}

function compactArgs(args) {
  if (!args || typeof args !== "object") return "";
  const parts = Object.entries(args).map(([k, v]) => `${k}=${trunc(typeof v === "string" ? v : JSON.stringify(v), 60)}`);
  return parts.join(", ");
}

/* ── models panel (MVP-1) ────────────────────────────────────────── */
/* Every control below is rendered from the schema the host sends for the
   model selected in that role — NVIDIA NIM changes its catalogue constantly
   and each family exposes a different surface, so nothing here is hardcoded
   per model. Types map to widgets: boolean → toggle, number → slider,
   integer → numeric field, enum → segmented control, array → tag field. */

const CAP_ICONS = { vision: "👁", reasoning: "🧠", tool_calling: "🛠", coding: "⌨" };

function capabilityChips(capabilities) {
  if (!capabilities) return "";
  return Object.entries(CAP_ICONS)
    .filter(([name]) => capabilities[name])
    .map(([, icon]) => icon)
    .join("");
}

function modelOptions(roleKey, selection, registryData) {
  const current = `${selection.provider || ""}::${selection.model || ""}`;
  let html = "";
  if (roleKey === "policy" && state && state.policy_builtin) {
    const active = !selection.provider || selection.provider === "typesafe";
    html += `<option value="builtin:jev"${active ? " selected" : ""}>TypeSafe Jev (built-in)</option>`;
  }
  const groups = [];
  if (registryData && registryData.providers) {
    for (const [provider, report] of Object.entries(registryData.providers)) {
      if (!report || !report.ok || !report.models || !report.models.length) continue;
      const opts = report.models
        .map((m) => {
          const value = `${provider}::${m.id}`;
          const caps = capabilityChips(m.capabilities);
          return `<option value="${escape(value)}"${value === current ? " selected" : ""}>${escape(m.displayName)}${caps ? " " + caps : ""}</option>`;
        })
        .join("");
      groups.push(`<optgroup label="${escape(provider)}">${opts}</optgroup>`);
    }
  }
  const inCatalogue = groups.some((g) => g.includes(`value="${escape(current)}"`)) || html.includes('value="builtin:jev"');
  if (current && !current.endsWith("::") && !inCatalogue) {
    const label = selection.display && selection.display !== "—" ? selection.display : `${selection.provider}:${selection.model}`;
    groups.push(`<optgroup label="current">${`<option value="${escape(current)}" selected>${escape(label)} (current)</option>`}</optgroup>`);
  }
  return html + groups.join("");
}

/* One widget per schema type (spec §5.3). */
function renderControl(roleKey, name, schema, value) {
  const attrs = `data-param="${escape(name)}" data-role="${escape(roleKey)}" data-type="${escape(schema.type)}"`;
  const label = escape(schema.label || name);
  const title = escape(schema.description || "");
  const mark = schema.verified ? '<i class="verified" title="Accepted by this endpoint in a real request">✓</i>' : "";
  let widget = "";
  if (schema.type === "enum") {
    const options = (schema.values || [])
      .map(
        (v) =>
          `<option value="${escape(v)}"${String(value) === String(v) ? " selected" : ""}>${escape((schema.labels && schema.labels[v]) || v)}</option>`,
      )
      .join("");
    widget = `<select ${attrs}><option value=""${value === undefined || value === null || value === "" ? " selected" : ""}>Default</option>${options}</select>`;
  } else if (schema.type === "boolean") {
    const checked = value === true || value === "on" || value === "true";
    widget = `<label class="toggle"><input type="checkbox" ${attrs}${checked ? " checked" : ""} /><span></span></label>`;
  } else if (schema.type === "number") {
    const shown = value === undefined || value === null || value === "" ? "" : value;
    widget =
      `<span class="slider"><input type="range" ${attrs} min="${schema.min}" max="${schema.max}" step="${schema.step}" value="${shown === "" ? schema.min : escape(shown)}"${shown === "" ? ' data-unset="1"' : ""} />` +
      `<output>${shown === "" ? "default" : escape(shown)}</output>` +
      `<button class="clear" data-clear="${escape(name)}" data-role="${escape(roleKey)}" title="Use the provider default">×</button></span>`;
  } else if (schema.type === "integer") {
    const shown = value === undefined || value === null ? "" : value;
    widget = `<input type="number" ${attrs} min="${schema.min}" max="${schema.max}" step="${schema.step || 1}" placeholder="default" value="${escape(shown)}" />`;
  } else if (schema.type === "array") {
    const shown = Array.isArray(value) ? value.join(", ") : value || "";
    widget = `<input type="text" ${attrs} placeholder="comma,separated" value="${escape(shown)}" />`;
  } else {
    widget = `<input type="text" ${attrs} placeholder="default" value="${escape(value ?? "")}" />`;
  }
  return `<label title="${title}">${label}${mark}</label>${widget}`;
}

function renderRoleSchema(role, sel) {
  const schema = sel.schema || {};
  const parameters = schema.parameters || {};
  const values = sel.params || {};
  const simple = [];
  const advanced = [];
  for (const [name, definition] of Object.entries(parameters)) {
    const html = renderControl(role.key, name, definition, values[name]);
    (definition.tier === "advanced" ? advanced : simple).push(html);
  }
  const unsupported = (schema.unsupported || []).length
    ? `<div class="hint dropped">hidden — rejected by this endpoint: ${escape((schema.unsupported || []).join(", "))}</div>`
    : "";
  const badge = schema.model
    ? `<span class="schema-id" title="Parameter surface resolved for this model">${escape(schema.schemaId || "")}</span>`
    : "";
  return `
    <div class="param-grid simple">${simple.join("")}</div>
    ${advanced.length ? `<details class="adv"><summary>advanced (${advanced.length})</summary><div class="param-grid">${advanced.join("")}</div></details>` : ""}
    ${unsupported}
    <div class="row schema-row">
      ${badge}
      <button class="probe" data-probe="${escape(role.key)}" title="Send one tiny request and record which parameters this model really accepts">Probe model</button>
    </div>`;
}

function renderModelsPanel() {
  if (!state || !state.selection || !state.schema) return;
  const signature = JSON.stringify([state.selection, state.presets, state.profiles, registry]);
  if (signature === modelsSignature) return; // don't rebuild while the user interacts
  modelsSignature = signature;
  const roles = state.schema.roles || [];
  const presets = state.presets || {};
  $("presets").innerHTML = Object.entries(presets)
    .map(
      ([key, p]) =>
        `<button class="chip" data-preset="${escape(key)}" title="${escape(p.description || "")}">${escape(p.label)}</button>`,
    )
    .join("");
  $("profiles").innerHTML = (state.profiles || [])
    .map(
      (name) =>
        `<span class="chip profile" data-profile="${escape(name)}" title="Click to apply this profile">${escape(name)}` +
        `<i class="del" data-profile-del="${escape(name)}" title="Delete profile">×</i></span>`,
    )
    .join("") || '<span class="hint">none saved yet</span>';
  $("model-roles").innerHTML = roles
    .map((role) => {
      const sel = state.selection[role.key] || {};
      const caps = capabilityChips((sel.schema || {}).capabilities);
      return `<div class="role-row">
        <div class="role-head"><b>${escape(role.label)}</b><span class="hint">${escape(role.hint || "")}</span><span class="caps">${caps}</span></div>
        <select class="model-select" data-role="${escape(role.key)}">${modelOptions(role.key, sel, registry)}</select>
        ${renderRoleSchema(role, sel)}
      </div>`;
    })
    .join("");
  renderRegistryStatus();
  wireModelsPanel();
}

function renderRegistryStatus() {
  const box = $("registry-status");
  if (!registry) {
    box.textContent = "catalogue not loaded";
    return;
  }
  const providers = Object.values(registry.providers || {});
  const ok = providers.filter((p) => p && p.ok);
  const models = ok.reduce((sum, p) => sum + (p.models ? p.models.length : 0), 0);
  const failed = providers.length - ok.length;
  const age = registry.fetchedAt ? `${Math.max(0, Math.round((Date.now() / 1000 - registry.fetchedAt) / 60))} min ago` : "";
  box.textContent = `${models} models · ${ok.length} providers${failed ? ` · ${failed} failed` : ""}${age ? ` · ${age}` : ""}`;
}

async function sendParam(role, name, value) {
  const reply = await browser.runtime.sendMessage({ cmd: "params", role, params: { [name]: value } });
  if (reply && reply.error) showError(reply.error);
}

function wireModelsPanel() {
  document.querySelectorAll(".model-select").forEach((select) => {
    select.addEventListener("change", async () => {
      const role = select.dataset.role;
      let provider = "";
      let model = "";
      if (select.value !== "builtin:jev") {
        [provider, model] = select.value.split("::");
      }
      const reply = await browser.runtime.sendMessage({ cmd: "select-model", role, provider, model });
      if (reply && reply.error) showError(reply.error);
    });
  });
  document.querySelectorAll("[data-param]").forEach((input) => {
    const read = () => {
      if (input.type === "checkbox") return input.checked;
      if (input.type === "range") return input.dataset.unset ? null : input.value;
      return input.value === "" ? null : input.value;
    };
    if (input.type === "range") {
      const output = input.parentElement.querySelector("output");
      input.addEventListener("input", () => {
        delete input.dataset.unset;
        output.textContent = input.value;
      });
    }
    input.addEventListener("change", () => sendParam(input.dataset.role, input.dataset.param, read()));
  });
  document.querySelectorAll("[data-clear]").forEach((button) => {
    button.addEventListener("click", () => sendParam(button.dataset.role, button.dataset.clear, null));
  });
  document.querySelectorAll("[data-probe]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "probing…";
      const reply = await browser.runtime.sendMessage({ cmd: "probe-model", role: button.dataset.probe });
      if (reply && reply.error) showError(reply.error);
    });
  });
  document.querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", async () => {
      const reply = await browser.runtime.sendMessage({ cmd: "params", preset: button.dataset.preset });
      if (reply && reply.error) showError(reply.error);
    });
  });
  document.querySelectorAll("[data-profile]").forEach((chip) => {
    chip.addEventListener("click", async () => {
      const reply = await browser.runtime.sendMessage({ cmd: "profile", action: "apply", name: chip.dataset.profile });
      if (reply && reply.error) showError(reply.error);
    });
  });
  document.querySelectorAll("[data-profile-del]").forEach((del) => {
    del.addEventListener("click", async (event) => {
      event.stopPropagation();
      const reply = await browser.runtime.sendMessage({ cmd: "profile", action: "delete", name: del.dataset.profileDel });
      if (reply && reply.error) showError(reply.error);
    });
  });
}

/* ── providers / error ───────────────────────────────────────────── */

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

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}

function showNotice(message) {
  const box = $("notice");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(showNotice.timer);
  showNotice.timer = setTimeout(() => {
    box.hidden = true;
  }, 12000);
}

function renderError(error) {
  if (error) showError(error);
}

/* ── approvals (MVP-4) ───────────────────────────────────────────── */

function showApproval(message) {
  approvalId = message.id;
  $("approval-command").textContent = message.command || "";
  $("approval").hidden = false;
}

async function answerApproval(approved) {
  if (!approvalId) return;
  const id = approvalId;
  approvalId = null;
  $("approval").hidden = true;
  await browser.runtime.sendMessage({ cmd: "approval", id, approved });
}

/* ── messages ────────────────────────────────────────────────────── */

browser.runtime.onMessage.addListener((message) => {
  if (message.type === "status") setConnection(message.connected);
  if (message.type === "state") {
    state = message.state;
    render();
  }
  if (message.type === "error") {
    // The next state broadcast carries the same error persistently; show it now.
    showError(message.message);
  }
  if (message.type === "checking") {
    $("providers").hidden = false;
    $("providers").innerHTML = '<div class="provider">⏳ Checking the model connections…</div>';
  }
  if (message.type === "models") {
    registry = message.registry || null;
    modelsSignature = ""; // force a rebuild with the fresh catalogue
    if (message.error) showError(message.error);
    if (state) render();
  }
  if (message.type === "notice") showNotice(message.message);
  if (message.type === "probe") {
    if (message.loading) {
      showNotice("Probing the model…");
    } else {
      const report = message.report || {};
      const dropped = (report.unsupported || []).length ? ` · unsupported: ${report.unsupported.join(", ")}` : "";
      showNotice(`${report.model || "model"} · ${report.schemaId || ""} · accepted: ${(report.verified || []).join(", ") || "none"}${dropped}`);
      modelsSignature = ""; // the schema changed: rebuild the controls
    }
  }
  if (message.type === "approval_request") showApproval(message);
  if (message.type === "delta") {
    $("thinking").textContent = message.text || "";
    $("thinking").hidden = false;
  }
});

$("run").addEventListener("click", async () => {
  const goal = $("goal").value.trim();
  if (!goal) return;
  $("error").hidden = true;
  $("error").textContent = "";
  if (state) state.error = null;
  const reply = await browser.runtime.sendMessage({ cmd: "run", goal });
  if (reply && reply.error) showError(reply.error);
});

$("check").addEventListener("click", async () => {
  $("error").hidden = true;
  const reply = await browser.runtime.sendMessage({ cmd: "check" });
  if (reply && reply.error) showError(reply.error);
});

$("stop").addEventListener("click", () => {
  browser.runtime.sendMessage({ cmd: "stop" });
});

$("refresh-models").addEventListener("click", async () => {
  $("registry-status").textContent = "refreshing…";
  const reply = await browser.runtime.sendMessage({ cmd: "models", refresh: true });
  if (reply && reply.error) showError(reply.error);
});

$("profile-save").addEventListener("click", async () => {
  const name = $("profile-name").value.trim();
  if (!name) return;
  const reply = await browser.runtime.sendMessage({ cmd: "profile", action: "save", name });
  if (reply && reply.error) showError(reply.error);
  else $("profile-name").value = "";
});

$("approval-yes").addEventListener("click", () => answerApproval(true));
$("approval-no").addEventListener("click", () => answerApproval(false));

(async () => {
  const status = await browser.runtime.sendMessage({ cmd: "status" });
  setConnection(status.connected);
  if (status.state) {
    state = status.state;
    render();
  }
  if (status.connected) {
    browser.runtime.sendMessage({ cmd: "models" }).catch(() => {}); // ask for the catalogue
  }
})();


/* ── browser target: live tab vs isolated Neko browser (MVP-5) ───── */

function renderTarget(data) {
  const mode = data.browserMode || "live";
  document.querySelectorAll("#target-toggle button").forEach((button) => {
    button.classList.toggle("on", button.dataset.target === mode);
  });
  const sandbox = data.sandbox || {};
  const session = sandbox.session;
  const status = $("sandbox-status");
  const actions = $("sandbox-actions");
  if (mode !== "sandbox") {
    status.textContent = "";
    actions.hidden = true;
    return;
  }
  actions.hidden = false;
  if (session) {
    const drivable = session.state === "running";
    status.textContent = drivable
      ? `isolated session up (${session.state})`
      : `session is ${session.state}: the agent cannot drive it (no CDP)`;
    $("sandbox-url").textContent = session.webUrl || "";
    $("sandbox-start").hidden = true;
    $("sandbox-stop").hidden = false;
    $("sandbox-open").hidden = false;
  } else {
    status.textContent = sandbox.available === false ? sandbox.reason || "Docker is not available" : "no session yet";
    $("sandbox-start").hidden = false;
    $("sandbox-start").disabled = sandbox.available === false;
    $("sandbox-stop").hidden = true;
    $("sandbox-open").hidden = true;
    $("sandbox-url").textContent = "";
  }
}

/* ── permission center: per-tool scopes (MVP-5) ──────────────────── */

function renderPermissions(permissions) {
  if (!permissions || !permissions.scopes) return;
  const signature = JSON.stringify(permissions);
  if (signature === permissionsSignature) return;
  permissionsSignature = signature;
  $("permission-rows").innerHTML = permissions.scopes
    .map((scope) => {
      const buttons = ["allow", "ask", "deny"]
        .map(
          (level) =>
            `<button data-scope="${escape(scope.key)}" data-level="${level}"` +
            `${scope.level === level ? ' class="on"' : ""}>${level}</button>`,
        )
        .join("");
      return `<div class="perm-row">
        <div class="perm-head"><b>${escape(scope.label)}</b><span class="hint">${escape(scope.hint || "")}</span></div>
        <div class="segmented small">${buttons}</div>
      </div>`;
    })
    .join("");
  document.querySelectorAll("#permission-rows [data-scope]").forEach((button) => {
    button.addEventListener("click", async () => {
      const reply = await browser.runtime.sendMessage({
        cmd: "permissions", scope: button.dataset.scope, level: button.dataset.level,
      });
      if (reply && reply.error) showError(reply.error);
    });
  });
}

$("permissions-reset").addEventListener("click", async () => {
  const reply = await browser.runtime.sendMessage({ cmd: "permissions", reset: true });
  if (reply && reply.error) showError(reply.error);
});

document.querySelectorAll("#target-toggle button").forEach((button) => {
  button.addEventListener("click", async () => {
    const reply = await browser.runtime.sendMessage({ cmd: "mode", mode: button.dataset.target });
    if (reply && reply.error) showError(reply.error);
  });
});

$("sandbox-start").addEventListener("click", async () => {
  const reply = await browser.runtime.sendMessage({ cmd: "sandbox", action: "start" });
  if (reply && reply.error) showError(reply.error);
});

$("sandbox-stop").addEventListener("click", async () => {
  const reply = await browser.runtime.sendMessage({ cmd: "sandbox", action: "stop" });
  if (reply && reply.error) showError(reply.error);
});

$("sandbox-open").addEventListener("click", async () => {
  const reply = await browser.runtime.sendMessage({ cmd: "sandbox", action: "open" });
  if (reply && reply.error) showError(reply.error);
});
