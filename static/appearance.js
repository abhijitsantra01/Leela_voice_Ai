// Independent presentation layer: no API calls or audio/session changes.
(() => {
  const root = document.documentElement;
  const systemTheme = matchMedia('(prefers-color-scheme: dark)');
  const systemMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const themeButton = document.getElementById('themeButton');
  const focusButton = document.getElementById('focusButton');
  const focusToggle = document.getElementById('focusToggle');
  const motionToggle = document.getElementById('reduceMotion');
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('leela.appearance') || '{}') || {}; } catch {}
  let theme = ['light', 'dark', 'system'].includes(saved.theme) ? saved.theme : 'system';
  let focused = saved.focus === true;
  const persist = () => {
    try { localStorage.setItem('leela.appearance', JSON.stringify({theme, focus: focused, quiet: motionToggle.checked})); } catch {}
  };
  function applyTheme() {
    const dark = theme === 'dark' || (theme === 'system' && systemTheme.matches);
    root.dataset.theme = dark ? 'dark' : 'light';
    themeButton.setAttribute('aria-pressed', String(dark));
    themeButton.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
    themeButton.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
    document.querySelectorAll('[data-theme-choice]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme)));
    document.querySelector('meta[name="theme-color"]').content = dark ? '#101820' : '#f5f9fd';
  }
  function applyFocus() {
    document.body.classList.toggle('focus-view', focused);
    focusButton.setAttribute('aria-pressed', String(focused));
    focusButton.setAttribute('aria-label', focused ? 'Exit focus view' : 'Enter focus view');
    focusButton.title = focused ? 'Exit focus view' : 'Enter focus view';
    focusToggle.checked = focused;
  }
  themeButton.addEventListener('click', () => {
    theme = root.dataset.theme === 'dark' ? 'light' : 'dark'; applyTheme(); persist();
  });
  document.querySelectorAll('[data-theme-choice]').forEach(button => button.addEventListener('click', () => {
    theme = button.dataset.themeChoice; applyTheme(); persist();
  }));
  focusButton.addEventListener('click', () => { focused = !focused; applyFocus(); persist(); });
  focusToggle.addEventListener('change', () => { focused = focusToggle.checked; applyFocus(); persist(); });
  motionToggle.checked = typeof saved.quiet === 'boolean' ? saved.quiet : systemMotion.matches;
  document.body.classList.toggle('quiet', motionToggle.checked);
  motionToggle.addEventListener('change', () => { document.body.classList.toggle('quiet', motionToggle.checked); persist(); });
  systemTheme.addEventListener('change', () => { if (theme === 'system') applyTheme(); });
  // Reflect settings changed in another tab; conversation state remains untouched.
  window.addEventListener('storage', event => {
    if (event.key !== 'leela.appearance') return;
    try {
      const next = JSON.parse(event.newValue || '{}') || {};
      theme = ['light','dark','system'].includes(next.theme) ? next.theme : 'system';
      focused = next.focus === true;
      motionToggle.checked = typeof next.quiet === 'boolean' ? next.quiet : systemMotion.matches;
      document.body.classList.toggle('quiet', motionToggle.checked);
      applyTheme(); applyFocus();
    } catch {}
  });
  applyTheme(); applyFocus();
})();
