/**
 * Action Executor & Element Highlighter for Firefox WebExtension.
 *
 * Executes clicks, text input, selects, scrolls directly in the active tab DOM
 * with 0ms IPC lag, and provides visual cues for user transparency.
 */
(() => {
  // Ensure overlay container exists for visual feedback
  let overlayContainer = document.getElementById('__ultrafast_agent_overlays__');
  let badgesContainer = document.getElementById('__ultrafast_agent_badges__');

  function getHighlightContainer() {
    if (!overlayContainer || !overlayContainer.isConnected) {
      overlayContainer = document.createElement('div');
      overlayContainer.id = '__ultrafast_agent_overlays__';
      overlayContainer.style.cssText =
        'position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; pointer-events: none; z-index: 2147483647;';
      document.documentElement.appendChild(overlayContainer);
    }
    return overlayContainer;
  }

  function flashHighlight(rect, color = '#10b981', label = '') {
    const container = getHighlightContainer();
    const box = document.createElement('div');
    box.style.cssText = `
      position: absolute;
      left: ${rect.x - 3}px;
      top: ${rect.y - 3}px;
      width: ${rect.w + 6}px;
      height: ${rect.h + 6}px;
      border: 3px solid ${color};
      border-radius: 6px;
      box-shadow: 0 0 16px ${color}88, inset 0 0 8px ${color}44;
      background: ${color}1a;
      transition: opacity 0.5s ease-out, transform 0.5s ease-out;
      transform: scale(1);
      opacity: 1;
      pointer-events: none;
    `;

    if (label) {
      const tag = document.createElement('span');
      tag.textContent = label;
      tag.style.cssText = `
        position: absolute;
        bottom: 100%;
        left: 0;
        background: ${color};
        color: #ffffff;
        font-family: system-ui, -apple-system, sans-serif;
        font-size: 11px;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        white-space: nowrap;
        margin-bottom: 2px;
      `;
      box.appendChild(tag);
    }

    container.appendChild(box);

    setTimeout(() => {
      box.style.opacity = '0';
      box.style.transform = 'scale(1.05)';
      setTimeout(() => box.remove(), 500);
    }, 600);
  }

  window.__executeAction = function(actionReq) {
    const cache = window.__jevFast;
    const kind = actionReq.kind || actionReq.operation?.toLowerCase();
    const action = actionReq.action || {};

    if (kind === 'scroll_down' || actionReq.operation === 'SCROLL_DOWN') {
      window.scrollBy({ top: 560, behavior: 'smooth' });
      return { success: true, executed: 'scroll_down' };
    }
    if (kind === 'scroll_up' || actionReq.operation === 'SCROLL_UP') {
      window.scrollBy({ top: -560, behavior: 'smooth' });
      return { success: true, executed: 'scroll_up' };
    }
    if (kind === 'wait' || actionReq.operation === 'WAIT') {
      return new Promise((resolve) => {
        setTimeout(() => resolve({ success: true, executed: 'wait' }), 400);
      });
    }

    // Resolve target element
    let element = null;
    if (action.node && cache?.nodes?.has(action.node)) {
      element = cache.nodes.get(action.node);
    }

    if (!element && actionReq.node && cache?.nodes?.has(actionReq.node)) {
      element = cache.nodes.get(actionReq.node);
    }

    if (!element) {
      return { success: false, error: 'Target element is no longer attached to DOM' };
    }

    // Scroll into view if needed
    const r = element.getBoundingClientRect();
    if (r.top < 0 || r.bottom > window.innerHeight || r.left < 0 || r.right > window.innerWidth) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    const freshRect = element.getBoundingClientRect();
    const rectInfo = { x: freshRect.x, y: freshRect.y, w: freshRect.width, h: freshRect.height };

    if (actionReq.operation === 'TYPE_TEXT' || kind === 'fill') {
      const textToType = actionReq.text ?? actionReq.value ?? '';
      flashHighlight(rectInfo, '#3b82f6', `TYPE: "${textToType}"`);

      element.focus();
      if ('select' in element && typeof element.select === 'function') {
        element.select();
      }

      // Input value update
      element.value = textToType;

      // Dispatch realistic DOM input and change events
      element.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
      element.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));

      return { success: true, executed: action.id || 'fill', text: textToType };
    }

    if (actionReq.operation === 'SELECT' || kind === 'select') {
      flashHighlight(rectInfo, '#8b5cf6', 'SELECT');
      if (element.tagName === 'SELECT' && actionReq.value) {
        element.value = actionReq.value;
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
        return { success: true, executed: action.id || 'select', value: actionReq.value };
      }
    }

    // Default: CLICK
    flashHighlight(rectInfo, '#10b981', 'CLICK');
    element.focus();

    // Standard pointer and mouse click sequence
    const mouseOpts = { bubbles: true, cancelable: true, view: window };
    element.dispatchEvent(new MouseEvent('pointerdown', mouseOpts));
    element.dispatchEvent(new MouseEvent('mousedown', mouseOpts));
    element.dispatchEvent(new MouseEvent('pointerup', mouseOpts));
    element.dispatchEvent(new MouseEvent('mouseup', mouseOpts));
    element.dispatchEvent(new MouseEvent('click', mouseOpts));

    return { success: true, executed: action.id || 'click' };
  };

  window.__toggleBadges = function(enable) {
    if (badgesContainer) {
      badgesContainer.remove();
      badgesContainer = null;
    }
    if (!enable) return false;

    const snapshot = window.__runSnapshot();
    if (!snapshot || !snapshot.elements) return false;

    badgesContainer = document.createElement('div');
    badgesContainer.id = '__ultrafast_agent_badges__';
    badgesContainer.style.cssText =
      'position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; pointer-events: none; z-index: 2147483646;';

    for (const el of snapshot.elements) {
      if (!el.rect || el.rect.w <= 0 || el.rect.h <= 0) continue;
      const badge = document.createElement('div');
      badge.textContent = `[${el.index}]`;
      badge.style.cssText = `
        position: absolute;
        left: ${el.rect.x}px;
        top: ${el.rect.y}px;
        background: #ef4444;
        color: #ffffff;
        font-family: system-ui, -apple-system, sans-serif;
        font-size: 11px;
        font-weight: 700;
        line-height: 1;
        padding: 2px 4px;
        border-radius: 3px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.5);
        pointer-events: none;
      `;
      badgesContainer.appendChild(badge);
    }

    document.documentElement.appendChild(badgesContainer);
    return true;
  };
})();
