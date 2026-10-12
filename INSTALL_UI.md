# Leela UI · Moonlight edition

UI-only overlay for your existing Leela AI v2 project.

## Install

1. Copy the contents of this ZIP's `static` folder into your existing `Leela_Ai/static` folder. Replace `index.html` and `style.css` when asked.
2. Keep all your other existing files, including `static/app.js` and `static/pcm-worklet.js`.
3. Run your app as usual, then refresh the browser with **Ctrl+F5**.

No dependency installation is needed. This ZIP does not contain a backend, API keys, audio files, or replacements for your voice/session logic. It requires your existing app; opening index.html directly will not run voice chat.

## Added

- Daylight, Moonlight and Automatic appearance. Automatic follows the device theme.
- A one-click light/dark toggle in the header, plus appearance choices in Settings.
- Five coordinated dark palettes, preserving each voice's colour identity.
- Focus view: removes the large introduction and tightens the studio layout. Voice selection, chat and model controls remain available.
- Remembered theme, focus and reduced-motion preferences using localStorage; blocked storage safely falls back to session-only settings.
- Appearance updates sync across tabs without touching conversation state.
- Softer transitions, refined message surfaces, active-listening indicator, accessible button labels and motion-reduction support.

## Files

- `static/index.html` — updated controls and presentation script links.
- `static/style.css` — existing base layout.
- `static/appearance.css` — light/dark voice palettes and focus view.
- `static/appearance-init.js` — applies the theme before first paint.
- `static/appearance.js` — UI preferences only; makes no API calls.

The earlier WebSocket cleanup fix stays in your existing app.py; no Python files are replaced.

Validation: JavaScript syntax and appearance state checks passed. Browser visual QA was unavailable in the build environment.
