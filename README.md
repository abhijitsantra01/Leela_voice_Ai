# Leela AI · Voice Studio v2

A clean, softly animated voice studio with five companion colours, live model switching, translation, captions, and a chat panel that scrolls without showing a scrollbar.

## Update your existing installation (PowerShell)

1. Stop the old server with **Ctrl+C**.
2. Extract the updated ZIP. Replace the project files in your existing `Leela_Ai` folder. **Keep your existing `.env` and `.venv`**; the ZIP contains neither.
3. In that folder, install the updated web dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade -r requirements-web.txt
.\.venv\Scripts\python.exe app.py
```

4. Open **http://localhost:8000** and press **Ctrl+F5** once to clear the previous UI from browser cache.

The `-r` is required: it tells pip to read the dependency file. `pip install requirements-web.txt` tries to install a package with that name and is incorrect.

## First-time setup

Python 3.12 or 3.13 is recommended. No frontend build or Node.js installation is needed to use the app.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
Copy-Item .env.example .env
notepad .env
```

Add your Gemini API key after `GEMINI_API_KEY=` and save. Then:

```powershell
.\.venv\Scripts\python.exe app.py
```

Open **http://localhost:8000** in Chrome or Edge. Click **Let's talk** and allow the microphone. **No wake word is needed.** Click **End session** to release microphone access. Future launches can use `start_windows.bat`.

If you already have `.env`, do not copy over it. If using Python 3.13, change `-3.12` to `-3.13`.

macOS/Linux: `python3 -m venv .venv`, `.venv/bin/pip install -r requirements-web.txt`, copy `.env.example` to `.env`, edit the key, then `.venv/bin/python app.py`.

## What's new

- A light, premium interface with soft colours, animated fluid orb, floating details and voice activity bars.
- **Aoede:** sky blue and white. **Kore:** lavender. **Puck:** mint. **Charon:** warm sand. **Fenrir:** peach.
- Click a companion to change voice during a call. The backend closes the previous Gemini connection and opens a new one with the actual selected voice. You remain in the same browser session, without another microphone permission prompt.
- Voice/model/language changes pause audio briefly. They are applied automatically; they are not an in-place Gemini voice mutation. Rapid changes are serialized, and the latest selection wins. Muting remains in effect through switching.
- Recent text transcript context is carried into chat connections (up to 40 entries, bounded to approximately 24,000 characters). Audio, hidden reasoning and provider session internals are not preserved. Displayed notes remain in the tab.
- Real model selection with capability-specific setup, speech translation and text-only live captions.
- Scroll the chat with a wheel, touch, trackpad or keyboard. Scrollbars stay hidden. Reading older messages pauses automatic following; use **Back to latest** to catch up.
- Voice volume, optional interruption, mute, reduced motion, transcript download, typed prompts in chat mode, and a supplied-recording player.

## Models

| Display name | API model ID | Behaviour |
| --- | --- | --- |
| Gemini 2.5 Flash Native Audio Dialog | `gemini-2.5-flash-native-audio-preview-12-2025` | Original conversational voice model |
| Gemini 3.1 Flash Live | `gemini-3.1-flash-live-preview` | Flash Live conversational model |
| Gemini 3.5 Live Translate | `gemini-3.5-live-translate-preview` | Microphone audio → translated speech and transcripts |
| Gemini 3.5 Transcribe Live | `gemini-3.5-transcribe-live` | Microphone audio → live captions; no spoken reply |
| Gemini 3.8 Live | `gemini-3.8-live` | Conversational voice |
| Gemini 3.8 Live Extended Thinking | `gemini-3.8-live-extended-thinking` | Conversational voice with background reasoning |

The requested “Gemini 3 Flash Live” family is shown under the verified current name **Gemini 3.1 Flash Live**, using its official endpoint. It is not mapped to the text-only `gemini-3-flash-preview` model.

The catalog uses documented model IDs, but access is not guaranteed for every key. Availability, retirement, billing and quotas are account-dependent. The “0 / Unlimited” values from an account dashboard are not hard-coded as universal free limits. Connection errors explain quota/access problems; the app never silently changes your chosen model.

**Translation:** choose English, Bengali or Hindi as the target. Selecting translation from Auto chooses English, visibly. This is an audio interpreter, not an assistant. Text prompts and companion voice selection are disabled because the model uses its own translation voice behaviour. Headphones are recommended; input continues while translated audio plays.

**Transcription:** Auto detects the spoken language; a language can also be selected. Interim captions are replaced with final transcripts, without speaking a reply. Companion voice selection and text prompts are disabled.

**Extended Thinking:** the app tracks `interaction_status`, so completion of one spoken utterance does not incorrectly end background reasoning. No external tools are configured.

Voice colours are an interface design choice, not a change to the model's personality or a guarantee of voice gender. The sample button plays the original supplied WAV, not a voice-specific preview.

## Configuration

```dotenv
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.5-flash-native-audio-preview-12-2025
GEMINI_VOICE=Aoede
```

`GOOGLE_API_KEY` is supported as a fallback. Existing `.env` preferences are respected. Changes to `.env` require a server restart. UI voice/model/language changes during a session apply automatically.

## Dependencies and original desktop mode

- `requirements-web.txt`: everything needed for this browser app; Google GenAI SDK is now **>=2.29.0,<3.0** for translation/transcription configuration.
- `AI_voice_chat_req.txt`: updated complete dependency list, including the original desktop packages.
- `requirements-dev.txt`: optional Python test dependencies. They are not needed to run the app.

The original `gemini_voice_test.py` remains included for compatibility, and retains its separate desktop wake-word behaviour. The redesigned browser app does not use it or require PocketSphinx. If you specifically want desktop mode:

```powershell
.\.venv\Scripts\python.exe -m pip install -r AI_voice_chat_req.txt
.\.venv\Scripts\python.exe gemini_voice_test.py
```

Desktop packages may need native compiler/PortAudio dependencies on some platforms. Use `requirements-web.txt` for the browser experience. The desktop script is intended for conversational audio models, not the specialized translation/caption modes. Running it overwrites `gemini_voice_reply.wav` with the latest response.

## Privacy and operating limits

API keys remain on the local Python server. Live audio and messages go to Google Gemini. The browser app does not save conversations or audio on the server. Notes exist in tab memory until exported; reloading the page clears them. During a voice/model switch, recent transcript context is resent to the chosen chat model. Ending and starting a new session resets model context even though previous notes remain displayed.

The local server binds to 127.0.0.1, checks request host and WebSocket origin, and allows one live session at a time. This is a personal local app, not an authenticated public service. Public hosting requires HTTPS, authentication and per-user quota controls. Browser microphone access requires localhost or HTTPS.

Audio is captured as mono 16 kHz PCM and played at 24 kHz. The studio pauses after two minutes without recognized user speech or typed messages. Optional interruptions work best with headphones. Google Fonts is used with local fallback fonts.

## Changed files

`app.py`, `static/index.html`, `static/style.css`, `static/app.js`, `AI_voice_chat_req.txt`, `requirements-web.txt`, `.env.example`, `README.md`, `tests/test_app.py`.

New: `model_catalog.py`, `tests/test_frontend.cjs`.

Preserved: `static/pcm-worklet.js`, `gemini_voice_test.py`, `gemini_voice_reply.wav`, `start_windows.bat`, `requirements-dev.txt`, `.gitignore`.

## Verification

Eight offline Python integration checks passed, including switching the live voice/model on the same WebSocket, closing the old upstream first, keeping context, and rejecting invalid settings without abandoning the current connection. All six model configurations validate against Google GenAI 2.29.0.

Node state-machine regression checks cover rapid voice changes, server acknowledgements, retained mute, specialized mode controls, chat scrolling, and background reasoning state. Python compilation and JavaScript syntax checks passed.

These tests use a mocked Gemini connection and DOM stubs, not real audio or browser rendering. Live Gemini access, actual microphone playback, and visual browser QA still require testing on your device.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# Optional, if Node.js is installed:
node tests/test_frontend.cjs
```

## Troubleshooting

- **Old UI:** stop the old server, replace the files, restart, then Ctrl+F5.
- **TranslationConfig or language_codes errors:** upgrade using `python -m pip install --upgrade -r requirements-web.txt` in the same environment running the server.
- **Voice selection unavailable:** translation and transcription do not use companion voices. Choose a chat model.
- **Model connection error:** verify access/quota in your account or choose another model. A model's presence in the catalog does not guarantee account access.
- **Microphone blocked:** allow microphone permissions in the browser and Windows settings.
- **Echo:** use headphones; leave interruptions off for ordinary chat.
- **Switch timeout:** the app ends capture and displays an error. Start again with a model your account supports.

## Model references

- https://ai.google.dev/gemini-api/docs/models
- https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-live-preview
- https://ai.google.dev/gemini-api/docs/live-api/capabilities
- https://ai.google.dev/gemini-api/docs/live-api/live-translate
- https://ai.google.dev/gemini-api/docs/live-api/live-transcribe
- https://ai.google.dev/gemini-api/docs/live-api/thinking
