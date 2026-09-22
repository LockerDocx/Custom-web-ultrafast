/**
 * Autonomous Browser Agent Controller for Firefox.
 *
 * Coordinates DOM snapshotting, LLM reasoning, and DOM action execution.
 */

const DEFAULT_SETTINGS = {
  provider: 'openrouter',
  model: 'deepseek/deepseek-chat',
  apiKey: '',
  baseUrl: 'https://openrouter.ai/api/v1',
  maxSteps: 30,
  highlightTargets: true
};

let agentState = {
  status: 'idle', // 'idle' | 'running' | 'step_done' | 'done' | 'blocked' | 'error'
  tabId: null,
  tabUrl: '',
  tabTitle: '',
  goal: '',
  stepCount: 0,
  maxSteps: 30,
  history: [],
  lastError: null,
  badgesEnabled: false,
  metrics: {
    domMs: 0,
    llmMs: 0,
    execMs: 0,
    totalStepMs: 0
  },
  settings: { ...DEFAULT_SETTINGS }
};

let autoRunTimer = null;
let isExecuting = false;

// Load persisted settings from storage
browser.storage.local.get('agent_settings').then((data) => {
  if (data && data.agent_settings) {
    agentState.settings = { ...DEFAULT_SETTINGS, ...data.agent_settings };
  }
});

function saveSettings(newSettings) {
  agentState.settings = { ...agentState.settings, ...newSettings };
  browser.storage.local.set({ agent_settings: agentState.settings });
}

function broadcastState() {
  browser.runtime.sendMessage({ type: 'STATE_UPDATED', state: agentState }).catch(() => {
    // Popup might be closed, which is completely normal
  });
}

async function getActiveTab() {
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  return tabs[0] || null;
}

async function ensureContentScripts(tabId) {
  try {
    // Inject snapshot.js and executor.js if not already present
    await browser.tabs.executeScript(tabId, { file: 'content/snapshot.js' });
    await browser.tabs.executeScript(tabId, { file: 'content/executor.js' });
  } catch (err) {
    throw new Error(`Cannot access tab ${tabId}. Is it an internal browser page (e.g. about:blank)? ${err.message}`);
  }
}

async function takeSnapshot(tabId) {
  const t0 = performance.now();
  await ensureContentScripts(tabId);
  const results = await browser.tabs.executeScript(tabId, {
    code: 'window.__runSnapshot ? window.__runSnapshot() : null;'
  });
  const domMs = Math.round(performance.now() - t0);

  if (!results || !results[0]) {
    throw new Error('Could not extract page DOM snapshot.');
  }

  return { snapshot: results[0], domMs };
}

async function executeActionInTab(tabId, actionPayload) {
  const t0 = performance.now();
  const scriptCode = `
    window.__executeAction ? window.__executeAction(${JSON.stringify(actionPayload)}) : { success: false, error: 'Executor script not ready' };
  `;
  const results = await browser.tabs.executeScript(tabId, { code: scriptCode });
  const execMs = Math.round(performance.now() - t0);
  return { result: results?.[0] || { success: false }, execMs };
}

function resolveAction(parsed, snapshot) {
  const op = String(parsed.operation || '').toUpperCase().trim();
  const rawTarget = String(parsed.target || '').replace(/[\[\]\s]/g, '');
  const text = parsed.text ? String(parsed.text) : null;

  if (op === 'DONE' || rawTarget.toUpperCase() === 'DONE') {
    return { type: 'DONE', label: 'Goal Completed', thought: parsed.thought };
  }
  if (op === 'BLOCKED' || rawTarget.toUpperCase() === 'BLOCKED') {
    return { type: 'BLOCKED', label: 'Agent Blocked', thought: parsed.thought };
  }
  if (op === 'WAIT' || rawTarget.toUpperCase() === 'WAIT') {
    return { type: 'WAIT', operation: 'WAIT', label: 'Wait for page update', thought: parsed.thought };
  }
  if (op === 'SCROLL_DOWN' || rawTarget.toUpperCase() === 'SCROLL_DOWN') {
    return { type: 'SCROLL', operation: 'SCROLL_DOWN', label: 'Scroll down', thought: parsed.thought };
  }
  if (op === 'SCROLL_UP' || rawTarget.toUpperCase() === 'SCROLL_UP') {
    return { type: 'SCROLL', operation: 'SCROLL_UP', label: 'Scroll up', thought: parsed.thought };
  }

  // Find matching element by index (e.g. '1', '2', '4:1')
  const elements = snapshot.elements || [];
  let matchedEl = elements.find((e) => e.index === rawTarget);

  // If not found directly, search digits
  if (!matchedEl) {
    const num = rawTarget.split(':')[0];
    matchedEl = elements.find((e) => e.index === num);
  }

  // If still not found and operation has targets, pick first element
  if (!matchedEl && elements.length > 0) {
    matchedEl = elements[0];
  }

  if (matchedEl) {
    const finalOp = op === 'TYPE_TEXT' && text !== null ? 'TYPE_TEXT' : (op === 'SELECT' ? 'SELECT' : 'CLICK');
    return {
      type: 'ELEMENT',
      operation: finalOp,
      target: matchedEl.index,
      node: matchedEl.node,
      action: { node: matchedEl.node, id: 'e' + matchedEl.index },
      text: text,
      label: `[${matchedEl.index}] ${finalOp} '${matchedEl.label}'`,
      thought: parsed.thought
    };
  }

  return { type: 'WAIT', operation: 'WAIT', label: 'Wait (fallback)', thought: parsed.thought };
}

async function runStep() {
  if (isExecuting) return;
  isExecuting = true;

  try {
    const tab = await getActiveTab();
    if (!tab) {
      throw new Error('No active browser tab found.');
    }
    agentState.tabId = tab.id;
    agentState.tabUrl = tab.url;
    agentState.tabTitle = tab.title;

    // 1. Snapshot DOM
    const { snapshot, domMs } = await takeSnapshot(tab.id);

    // 2. Call LLM
    const { parsed, latencyMs: llmMs, model, usage } = await callProviderLLM({
      provider: agentState.settings.provider,
      model: agentState.settings.model,
      apiKey: agentState.settings.apiKey,
      baseUrl: agentState.settings.baseUrl,
      snapshot: snapshot,
      goal: agentState.goal,
      history: agentState.history
    });

    // 3. Resolve Action
    const actionPlan = resolveAction(parsed, snapshot);

    // 4. Execute Action
    let execMs = 0;
    if (actionPlan.type === 'ELEMENT' || actionPlan.type === 'SCROLL' || actionPlan.type === 'WAIT') {
      const execResult = await executeActionInTab(tab.id, actionPlan);
      execMs = execResult.execMs;
    }

    agentState.stepCount += 1;
    const totalStepMs = domMs + llmMs + execMs;

    agentState.metrics = {
      domMs: domMs,
      llmMs: llmMs,
      execMs: execMs,
      totalStepMs: totalStepMs
    };

    const historyEntry = {
      step: agentState.stepCount,
      action: actionPlan.label,
      operation: actionPlan.operation || actionPlan.type,
      text: actionPlan.text || null,
      thought: actionPlan.thought || '',
      url: snapshot.url,
      metrics: { ...agentState.metrics },
      model: model,
      timestamp: Date.now()
    };
    agentState.history.push(historyEntry);

    // Check termination
    if (actionPlan.type === 'DONE') {
      agentState.status = 'done';
      stopAgentLoop();
    } else if (actionPlan.type === 'BLOCKED') {
      agentState.status = 'blocked';
      stopAgentLoop();
    } else if (agentState.stepCount >= agentState.settings.maxSteps) {
      agentState.status = 'done';
      stopAgentLoop();
    } else {
      agentState.status = agentState.status === 'running' ? 'running' : 'step_done';
    }

    broadcastState();

    // Settle pause before next automatic step
    if (agentState.status === 'running') {
      autoRunTimer = setTimeout(() => {
        isExecuting = false;
        runStep();
      }, 400);
    }
  } catch (err) {
    agentState.status = 'error';
    agentState.lastError = err.message || String(err);
    stopAgentLoop();
    broadcastState();
  } finally {
    if (agentState.status !== 'running') {
      isExecuting = false;
    }
  }
}

function startAgentLoop(goal) {
  if (goal) agentState.goal = goal;
  if (!agentState.goal.trim()) {
    throw new Error('Please enter a goal first.');
  }
  agentState.status = 'running';
  agentState.lastError = null;
  broadcastState();
  runStep();
}

function stopAgentLoop() {
  if (autoRunTimer) {
    clearTimeout(autoRunTimer);
    autoRunTimer = null;
  }
  if (agentState.status === 'running') {
    agentState.status = 'idle';
  }
  isExecuting = false;
  broadcastState();
}

function resetAgent() {
  stopAgentLoop();
  agentState.stepCount = 0;
  agentState.history = [];
  agentState.status = 'idle';
  agentState.lastError = null;
  agentState.metrics = { domMs: 0, llmMs: 0, execMs: 0, totalStepMs: 0 };
  broadcastState();
}

async function toggleBadges(enable) {
  agentState.badgesEnabled = enable;
  const tab = await getActiveTab();
  if (tab) {
    await ensureContentScripts(tab.id);
    await browser.tabs.executeScript(tab.id, {
      code: `window.__toggleBadges ? window.__toggleBadges(${enable}) : false;`
    });
  }
  broadcastState();
}

// Runtime message listener for UI commands
browser.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case 'GET_STATE':
      sendResponse({ state: agentState, providers: PROVIDER_METADATA });
      break;

    case 'START':
      try {
        if (msg.settings) saveSettings(msg.settings);
        startAgentLoop(msg.goal);
        sendResponse({ success: true });
      } catch (e) {
        sendResponse({ success: false, error: e.message });
      }
      break;

    case 'STEP':
      try {
        if (msg.settings) saveSettings(msg.settings);
        if (msg.goal) agentState.goal = msg.goal;
        runStep();
        sendResponse({ success: true });
      } catch (e) {
        sendResponse({ success: false, error: e.message });
      }
      break;

    case 'STOP':
      stopAgentLoop();
      sendResponse({ success: true });
      break;

    case 'RESET':
      resetAgent();
      sendResponse({ success: true });
      break;

    case 'UPDATE_SETTINGS':
      saveSettings(msg.settings);
      sendResponse({ success: true, settings: agentState.settings });
      break;

    case 'TOGGLE_BADGES':
      toggleBadges(msg.enable).then(() => sendResponse({ success: true, enabled: msg.enable }));
      return true; // async response

    default:
      sendResponse({ error: 'Unknown message type' });
  }
  return true;
});
