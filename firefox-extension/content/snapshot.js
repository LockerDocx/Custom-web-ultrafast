/**
 * Ultrafast DOM Snapshot Engine for Firefox WebExtension.
 *
 * Scans visible interactive elements, builds indexed element representations,
 * extracts text and action spaces in < 5ms without slow vision or screenshot encoding.
 */
(() => {
  window.__runSnapshot = function() {
    if (!document.body) return null;
    const cache = (window.__jevFast ||= { ids: new WeakMap(), nodes: new Map(), next: 1 });

    const identity = (e) => {
      if (!cache.ids.has(e)) cache.ids.set(e, cache.next++);
      const id = cache.ids.get(e);
      cache.nodes.set(id, e);
      return id;
    };

    // Clean disconnected nodes
    for (const [id, e] of cache.nodes) {
      if (!e.isConnected) cache.nodes.delete(id);
    }

    const safe = (e) => !['password', 'file', 'hidden'].includes(e.type);
    const visible = (e) => {
      if (!e || e.closest('[aria-hidden="true"],[inert]')) return false;
      if (typeof e.checkVisibility === 'function') {
        return e.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
      }
      const r = e.getBoundingClientRect();
      const style = window.getComputedStyle(e);
      return r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && parseFloat(style.opacity || '1') > 0.05;
    };

    const name = (e, seen = new Set()) => {
      if (!e || seen.has(e)) return '';
      seen.add(e);
      const referenced = (e.getAttribute('aria-labelledby') || '')
        .split(/\s+/)
        .map((id) => name(document.getElementById(id), seen))
        .filter(Boolean)
        .join(' ');
      return (
        referenced ||
        e.getAttribute('aria-label') ||
        [...(e.labels || [])].map((l) => name(l, seen)).filter(Boolean).join(' ') ||
        (['button', 'submit', 'reset'].includes(e.type) ? e.value : '') ||
        e.getAttribute('alt') ||
        (e.tagName === 'INPUT'
          ? ''
          : [...e.childNodes]
              .map((n) =>
                n.nodeType === 3
                  ? n.textContent
                  : n.nodeType === 1 && n.getAttribute('aria-hidden') !== 'true'
                  ? name(n, seen)
                  : ''
              )
              .join(' ')
              .trim()) ||
        e.getAttribute('title') ||
        e.getAttribute('placeholder') ||
        ''
      );
    };

    const roles = [
      'button', 'link', 'checkbox', 'radio', 'switch', 'tab',
      'menuitem', 'menuitemradio', 'option', 'gridcell',
      'combobox', 'textbox', 'searchbox', 'spinbutton'
    ];
    const selector =
      'a[href],button,input,textarea,select,summary,[contenteditable="true"],' +
      roles.map((r) => `[role="${r}"]`).join(',');

    const role = (e) => {
      const explicit = e.getAttribute('role');
      if (roles.includes(explicit)) return explicit;
      if (e.tagName === 'BUTTON' || e.tagName === 'SUMMARY') return 'button';
      if (e.tagName === 'A') return 'link';
      if (e.tagName === 'SELECT') return 'combobox';
      if (e.tagName === 'TEXTAREA' || e.isContentEditable) return 'textbox';
      if (e.tagName === 'INPUT') {
        if (['checkbox', 'radio'].includes(e.type)) return e.type;
        if (['button', 'submit', 'reset', 'image'].includes(e.type)) return 'button';
        if (e.type === 'search') return 'searchbox';
        if (e.type === 'number') return 'spinbutton';
        if (['text', 'email', 'url', 'tel'].includes(e.type)) return 'textbox';
      }
      return null;
    };

    cache.pageKey = () => [
      performance.timeOrigin,
      location.href,
      window.scrollX,
      window.scrollY,
      window.innerWidth,
      window.innerHeight,
      [...document.querySelectorAll('input,textarea,select')]
        .filter(safe)
        .map((e) => [identity(e), e.value, e.checked, e.selectedIndex, e.disabled, e.readOnly])
    ];

    cache.guard = (e) => {
      if (!e?.isConnected || !visible(e)) return null;
      const scope = e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
      return [
        identity(e),
        role(e),
        name(e),
        e.value ?? null,
        e.checked ?? null,
        e.selectedIndex ?? null,
        e.readOnly ?? null,
        e.matches(':disabled'),
        e.getAttribute('aria-disabled'),
        e.getAttribute('aria-expanded'),
        e.getAttribute('aria-checked'),
        e.getAttribute('aria-selected'),
        e.getAttribute('href'),
        scope?.innerText?.slice(0, 6000) || ''
      ];
    };

    const actions = [];
    const elementsList = [];
    let elementIndex = 1;

    for (const e of document.querySelectorAll(selector)) {
      if (!safe(e) || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
      const r = e.getBoundingClientRect();
      const x = r.x + r.width / 2;
      const y = r.y + r.height / 2;
      const rname = role(e);
      if (!rname || r.width <= 0 || r.height <= 0 || x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) continue;
      if (rname === 'gridcell' && e.querySelector('button,[role="button"]')) continue;

      const nodeId = identity(e);
      const strIdx = String(elementIndex++);
      const base = {
        node: nodeId,
        role: rname,
        label: name(e) || rname,
        rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }
      };

      for (const key of ['checked', 'selected', 'expanded']) {
        const value = e.getAttribute(`aria-${key}`);
        if (value !== null) base[key] = value;
      }
      if (['checkbox', 'radio'].includes(e.type)) base.checked = String(e.checked);

      if (e.tagName === 'SELECT') {
        const opts = [];
        let optNum = 1;
        for (const o of e.options) {
          if (!o.disabled && !o.closest('optgroup[disabled]')) {
            const optTarget = `${strIdx}:${optNum++}`;
            opts.push({ index: optTarget, label: o.label || o.text, value: o.value });
            if (!o.selected) {
              actions.push({
                ...base,
                kind: 'select',
                value: o.value,
                target: optTarget,
                current_value: [...e.selectedOptions].map((so) => so.label).join(', '),
                label: `${base.label} → ${o.label || o.text}`
              });
            }
          }
        }
        elementsList.push({
          index: strIdx,
          node: nodeId,
          role: rname,
          label: base.label,
          value: [...e.selectedOptions].map((so) => so.label).join(', '),
          operations: ['SELECT'],
          options: opts,
          rect: base.rect
        });
      } else {
        const editable =
          !e.readOnly &&
          e.getAttribute('aria-readonly') !== 'true' &&
          (['textbox', 'searchbox', 'spinbutton'].includes(rname) ||
            (rname === 'combobox' && ['INPUT', 'TEXTAREA'].includes(e.tagName)));
        const val = 'value' in e ? String(e.value) : e.isContentEditable || rname === 'combobox' ? e.innerText.trim() : '';

        const ops = [];
        if (editable) {
          ops.push('TYPE_TEXT');
          actions.push({ ...base, kind: 'fill', target: strIdx, value: val });
        }
        ops.push('CLICK');
        actions.push({ ...base, kind: 'click', target: strIdx, value: val, label: editable ? `Open ${base.label}` : base.label });

        elementsList.push({
          index: strIdx,
          node: nodeId,
          role: rname,
          label: base.label,
          value: val,
          operations: ops,
          rect: base.rect
        });
      }
    }

    // Extract visible page text
    const words = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    let node, length = 0;
    while ((node = walker.nextNode()) && length < 6000) {
      const val = node.textContent.trim();
      const parent = node.parentElement;
      if (!val || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
      range.selectNodeContents(node);
      const r = range.getBoundingClientRect();
      if (r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth) {
        words.push(val);
        length += val.length;
      }
    }
    const text = words.join('\n').slice(0, 6000);
    const height = document.documentElement.scrollHeight;
    const scrollY = window.scrollY;
    const innerHeight = window.innerHeight;

    // Standard control actions
    actions.splice(250);
    actions.forEach((a, i) => (a.id = 'e' + (i + 1)));

    if (scrollY + innerHeight < height - 2) {
      actions.push({ id: 'scroll_down', kind: 'scroll', label: 'Scroll down', delta: 560 });
    }
    if (scrollY > 0) {
      actions.push({ id: 'scroll_up', kind: 'scroll', label: 'Scroll up', delta: -560 });
    }
    actions.push({ id: 'wait', kind: 'wait', label: 'Wait for page to update' });

    return {
      url: location.href,
      title: document.title,
      w: window.innerWidth,
      h: window.innerHeight,
      text: text,
      scroll: { y: scrollY, height: height },
      elements: elementsList,
      actions: actions,
      pageKey: cache.pageKey(),
      timestamp: Date.now()
    };
  };

  return window.__runSnapshot();
})();
