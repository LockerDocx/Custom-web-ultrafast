/**
 * Popup UI Controller for Ultrafast Web Agent Firefox Extension.
 */

const $ = (id) => document.getElementById(id);

let currentProviders = {};
let isKeyVisible = false;

// Initialize on popup load
document.addEventListener('DOMContentLoaded', async () => {
  setupEventListeners();
  await refreshState();
});

// Listen for background state broadcasts
browser.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'STATE_UPDATED') {
    renderState(msg.state);
  }
});

function setupEventListeners() {
  // Provider dropdown change
  $('provider-select').addEventListener('change', (e) => {
    const provKey = e.target.value;
    updateProviderUI(provKey);
    saveCurrentSettings();
  });

  // Settings change auto-save
  $('api-key').addEventListener('input', () => saveCurrentSettings());
  $('base-url').addEventListener('input', () => saveCurrentSettings());
  $('model-name').addEventListener('input', () => saveCurrentSettings());

  // Password visibility toggle
  $('toggle-key-visibility').addEventListener('click', () => {
    isKeyVisible = !isKeyVisible;
    $('api-key').type = isKeyVisible ? 'text' : 'password';
    $('toggle-key-visibility').textContent = isKeyVisible ? '🙈' : '👁';
  });

  // Preset buttons
  document.querySelectorAll('.preset-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const preset = btn.getAttribute('data-preset');
      if (preset) {
        $('goal-input').value = preset;
      }
    });
  });

  // Control buttons
  $('btn-start').addEventListener('click', () => {
    const goal = $('goal-input').value.trim();
    if (!goal) {
      showError('Por favor escribe un objetivo para el agente.');
      return;
    }
    clearError();
    saveCurrentSettings();
    browser.runtime.sendMessage({
      type: 'START',
      goal: goal,
      settings: getFormSettings()
    }).then(handleActionResponse);
  });

  $('btn-step').addEventListener('click', () => {
    const goal = $('goal-input').value.trim();
    if (!goal) {
      showError('Por favor escribe un objetivo para el agente.');
      return;
    }
    clearError();
    saveCurrentSettings();
    browser.runtime.sendMessage({
      type: 'STEP',
      goal: goal,
      settings: getFormSettings()
    }).then(handleActionResponse);
  });

  $('btn-stop').addEventListener('click', () => {
    browser.runtime.sendMessage({ type: 'STOP' });
  });

  $('btn-reset').addEventListener('click', () => {
    browser.runtime.sendMessage({ type: 'RESET' });
  });

  // Badge overlay toggle
  $('chk-badges').addEventListener('change', (e) => {
    browser.runtime.sendMessage({
      type: 'TOGGLE_BADGES',
      enable: e.target.checked
    });
  });
}

function getFormSettings() {
  return {
    provider: $('provider-select').value,
    apiKey: $('api-key').value.trim(),
    baseUrl: $('base-url').value.trim(),
    model: $('model-name').value.trim()
  };
}

function saveCurrentSettings() {
  const settings = getFormSettings();
  browser.runtime.sendMessage({
    type: 'UPDATE_SETTINGS',
    settings: settings
  });
}

function handleActionResponse(res) {
  if (res && res.error) {
    showError(res.error);
  }
}

function showError(msg) {
  const errBox = $('error-box');
  errBox.textContent = msg;
  errBox.hidden = false;
}

function clearError() {
  $('error-box').hidden = true;
}

function updateProviderUI(provKey, customModel = null) {
  const meta = currentProviders[provKey];
  if (!meta) return;

  $('active-provider-badge').textContent = meta.name;
  $('base-url').value = meta.baseUrl;

  const currentModel = customModel || meta.defaultModel;
  $('model-name').value = currentModel;

  // Render recommended model chips
  const chipsContainer = $('model-chips');
  chipsContainer.innerHTML = '';
  (meta.models || []).forEach((m) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = `chip ${m === currentModel ? 'active' : ''}`;
    chip.textContent = m.split('/').pop();
    chip.title = m;
    chip.addEventListener('click', () => {
      $('model-name').value = m;
      document.querySelectorAll('.model-chips .chip').forEach((c) => c.classList.remove('active'));
      chip.classList.add('active');
      saveCurrentSettings();
    });
    chipsContainer.appendChild(chip);
  });
}

async function refreshState() {
  const res = await browser.runtime.sendMessage({ type: 'GET_STATE' });
  if (!res) return;

  currentProviders = res.providers || {};
  const state = res.state || {};
  const settings = state.settings || {};

  // Populate provider settings
  if (settings.provider && $('provider-select')) {
    $('provider-select').value = settings.provider;
  }
  if (settings.apiKey) {
    $('api-key').value = settings.apiKey;
  }

  updateProviderUI(settings.provider || 'openrouter', settings.model);

  if (settings.baseUrl) {
    $('base-url').value = settings.baseUrl;
  }
  if (state.goal && !$('goal-input').value) {
    $('goal-input').value = state.goal;
  }

  $('chk-badges').checked = !!state.badgesEnabled;

  renderState(state);
}

function renderState(state) {
  if (!state) return;

  // Status indicator
  const dot = $('status-dot');
  const txt = $('status-text');
  dot.className = 'status-dot';

  if (state.status === 'running') {
    dot.classList.add('running');
    txt.textContent = 'Ejecutando...';
  } else if (state.status === 'done') {
    txt.textContent = 'Completado ✓';
  } else if (state.status === 'blocked') {
    dot.classList.add('error');
    txt.textContent = 'Bloqueado ⚠️';
  } else if (state.status === 'error') {
    dot.classList.add('error');
    txt.textContent = 'Error';
  } else if (state.status === 'step_done') {
    txt.textContent = 'Paso listo';
  } else {
    txt.textContent = 'Listo';
  }

  // Button states
  const isRunning = state.status === 'running';
  $('btn-start').disabled = isRunning;
  $('btn-step').disabled = isRunning;
  $('btn-stop').disabled = !isRunning;

  // Metrics
  const m = state.metrics || { domMs: 0, llmMs: 0, execMs: 0, totalStepMs: 0 };
  $('metric-dom').textContent = `${m.domMs} ms`;
  $('metric-llm').textContent = `${m.llmMs} ms`;
  $('metric-exec').textContent = `${m.execMs} ms`;
  $('metric-total').textContent = `${m.totalStepMs} ms`;

  // Error message
  if (state.lastError) {
    showError(state.lastError);
  } else {
    clearError();
  }

  // History list
  renderHistory(state.history || []);
}

function renderHistory(history) {
  const container = $('history-list');
  const countEl = $('step-count');
  countEl.textContent = `${history.length} pasos`;

  if (!history.length) {
    container.innerHTML = `
      <div class="empty-state">
        Escribe un objetivo y pulsa <b>Iniciar</b> o <b>Paso</b> para comenzar la navegación autónoma.
      </div>
    `;
    return;
  }

  container.innerHTML = '';
  // Show most recent steps first
  const reversed = [...history].reverse();

  reversed.forEach((entry) => {
    const item = document.createElement('div');
    item.className = 'history-entry';

    const opKey = (entry.operation || '').toLowerCase();
    const thoughtHtml = entry.thought ? `<div class="entry-thought">"${escapeHtml(entry.thought)}"</div>` : '';
    const textHtml = entry.text ? `<div class="entry-text">Texto: <b>"${escapeHtml(entry.text)}"</b></div>` : '';
    const latency = entry.metrics ? `${entry.metrics.totalStepMs}ms (LLM: ${entry.metrics.llmMs}ms)` : '';

    item.innerHTML = `
      <div class="entry-head">
        <span class="entry-step">#${entry.step}</span>
        <span class="entry-badge ${opKey}">${escapeHtml(entry.operation || 'ACTION')}</span>
        <span class="entry-latency">${latency}</span>
      </div>
      <div class="entry-action">${escapeHtml(entry.action || '')}</div>
      ${textHtml}
      ${thoughtHtml}
    `;

    container.appendChild(item);
  });
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
