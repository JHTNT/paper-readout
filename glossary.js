(() => {
  const panel = document.querySelector('#term-panel');
  if (!panel) return;
  const entries = [...document.querySelector('#glossary-data').content.querySelectorAll('.glossary-entry')];
  const entryById = new Map(entries.map(entry => [entry.id, entry]));
  const aliases = new Map();
  entries.forEach(entry => {
    const names = [entry.querySelector('dt [lang="en"]'),
      entry.querySelector('.term-zh'), entry.querySelector('.term-full-name [lang="en"]')];
    names.forEach(node => {
      const name = node?.textContent.trim();
      if (name && !aliases.has(name)) aliases.set(name, entry.id);
    });
  });
  if (!aliases.size) return;

  const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const alternatives = [...aliases.keys()].sort((a, b) => b.length - a.length).map(name => {
    const start = /^[A-Za-z0-9_]/.test(name) ? '(?<![A-Za-z0-9_])' : '';
    const end = /[A-Za-z0-9_]$/.test(name) ? '(?![A-Za-z0-9_])' : '';
    return start + escape(name) + end;
  });
  const pattern = new RegExp(alternatives.join('|'), 'g');
  const selector = 'blockquote, .translation, .annotation > p:not(.passage-label), '
    + '.visual-caption span, .visual-explanation p, .table-notes';

  document.querySelectorAll('.pair').forEach(block => {
    const seen = new Set();
    block.querySelectorAll(selector).forEach(container => {
      const blocked = [];
      let offset = 0;
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const end = offset + node.length;
        if (node.parentElement.closest('a, button, .katex, math, script, style')) {
          blocked.push([offset, end]);
        }
        offset = end;
      }
      const text = container.textContent;
      // Protect raw LaTeX too, when KaTeX hasn't loaded or is unavailable.
      for (const math of text.matchAll(/\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/g)) {
        blocked.push([math.index, math.index + math[0].length]);
      }
      for (const match of text.matchAll(pattern)) {
        const end = match.index + match[0].length;
        if (!blocked.some(([a, b]) => match.index < b && end > a)) {
          seen.add(aliases.get(match[0]));
        }
      }
    });
    if (!seen.size) return;
    const row = document.createElement('div');
    row.className = 'block-terms';
    row.setAttribute('role', 'group');
    row.setAttribute('aria-label', '本段名詞');
    const label = document.createElement('span');
    label.className = 'block-terms-label';
    label.textContent = '本段名詞';
    row.append(label);
    seen.forEach(id => {
      const entry = entryById.get(id);
      const trigger = document.createElement('button');
      trigger.type = 'button';
      trigger.className = 'term-trigger';
      trigger.dataset.termId = id;
      trigger.textContent = entry.querySelector('dt [lang="en"]').textContent;
      trigger.setAttribute('aria-label', '查看名詞解釋：' + trigger.textContent);
      trigger.setAttribute('aria-controls', 'term-panel');
      trigger.setAttribute('aria-expanded', 'false');
      row.append(trigger);
    });
    block.querySelector('.annotation')?.append(row);
  });

  const content = panel.querySelector('.term-panel-content');
  const hover = window.matchMedia('(hover: hover)');
  let activeTrigger = null;
  let pinned = false;
  let hoverTimer;
  function cancelTimer() { clearTimeout(hoverTimer); }
  function positionPanel() {
    if (!activeTrigger || panel.hidden) return;
    const anchor = activeTrigger.getBoundingClientRect();
    const bounds = panel.getBoundingClientRect();
    const left = Math.max(16, Math.min(anchor.left, innerWidth - bounds.width - 16));
    let top = anchor.top - bounds.height - 10;
    if (top < 16) top = anchor.bottom + 10;
    top = Math.max(16, Math.min(top, innerHeight - bounds.height - 16));
    panel.style.left = left + 'px';
    panel.style.top = top + 'px';
  }
  function dismiss(restoreFocus = false) {
    cancelTimer();
    panel.hidden = true;
    if (activeTrigger) {
      activeTrigger.setAttribute('aria-expanded', 'false');
      if (restoreFocus) activeTrigger.focus({ preventScroll: true });
      activeTrigger = null;
    }
    pinned = false;
  }
  function show(trigger, pin = false) {
    cancelTimer();
    const entry = entryById.get(trigger.dataset.termId);
    if (activeTrigger) activeTrigger.setAttribute('aria-expanded', 'false');
    activeTrigger = trigger;
    pinned = pin;
    trigger.setAttribute('aria-expanded', 'true');
    const copy = entry.cloneNode(true);
    copy.removeAttribute('id');
    content.replaceChildren(copy);
    if (typeof renderMathInElement === 'function') {
      renderMathInElement(content, {
        delimiters: [{left:'\\[', right:'\\]', display:true}, {left:'\\(', right:'\\)', display:false}],
        throwOnError:false, trust:false,
      });
    }
    panel.hidden = false;
    panel.scrollTop = 0;
    positionPanel();
    if (pin) panel.focus({ preventScroll: true });
  }
  function scheduleDismiss() {
    cancelTimer();
    if (!pinned) hoverTimer = setTimeout(() => dismiss(), 220);
  }
  document.querySelectorAll('.term-trigger').forEach(trigger => {
    trigger.addEventListener('mouseenter', () => {
      if (!hover.matches || pinned) return;
      cancelTimer();
      hoverTimer = setTimeout(() => show(trigger), 180);
    });
    trigger.addEventListener('mouseleave', scheduleDismiss);
  });
  panel.addEventListener('mouseenter', cancelTimer);
  panel.addEventListener('mouseleave', scheduleDismiss);
  document.addEventListener('click', event => {
    const trigger = event.target.closest('.term-trigger');
    if (trigger) show(trigger, true);
    else if (!panel.contains(event.target)) dismiss();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) {
      event.preventDefault();
      dismiss(pinned);
    }
  });
  window.addEventListener('resize', positionPanel);
  window.addEventListener('scroll', event => {
    if (panel.hidden || panel.contains(event.target)) return;
    if (pinned) positionPanel();
    else dismiss();
  }, true);
})();
