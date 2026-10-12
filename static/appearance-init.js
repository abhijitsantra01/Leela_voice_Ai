// Apply appearance before the page paints. Stores presentation preferences only.
(() => {
  let prefs = {};
  try { prefs = JSON.parse(localStorage.getItem('leela.appearance') || '{}') || {}; } catch {}
  const choice = ['light', 'dark', 'system'].includes(prefs.theme) ? prefs.theme : 'system';
  document.documentElement.dataset.theme = choice === 'system'
    ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : choice;
})();
