import argparse
import asyncio
import math
import os
import queue
import re
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
INPUT_RATE = 16_000
OUTPUT_RATE = 24_000
CHUNK_SECONDS = 0.1
END_OF_SPEECH_SILENCE_MS = 250
IDLE_SLEEP_SECONDS = 120
WAKE_CONTINUATION_START_TIMEOUT_SECONDS = 0.7
WAKE_CONTINUATION_SILENCE_CHUNKS = 6
WAKE_CONTINUATION_MAX_SECONDS = 12
WAKE_CONTINUATION_PREROLL_CHUNKS = 5
SPEECH_PREFIX_PADDING_MS = 120
TONE_DURATION_SECONDS = 0.12
TONE_VOLUME = 0.18
WAKE_TONE = (660,)
SLEEP_TONE = (660, 440)
END_TURN = object()
WAKE_SEARCH = "leela_wake"
WAKE_WORDS = (
    "LEELA",
    "HII LEELA",
    "HI LEELA",
    "HEY LEELA",
    "HII LELA",
    "HI LELA",
    "HEY LELA",
    "HII LILA",
    "HI LILA",
    "HEY LILA",
)
LIVE_VOICES = ("Aoede", "Charon", "Fenrir", "Kore", "Puck")
NON_SPEECH_TRANSCRIPTS = {
    "background noise",
    "inaudible",
    "noise",
    "silence",
    "static",
    "unintelligible",
}


def _play_tone_sequence(
    sd, frequencies: tuple[int, ...], output_device: int, sample_rate: int
) -> None:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Audio tones need numpy. Install it with "
            "`python -m pip install numpy` in the Python environment "
            "you use to run this script."
        ) from exc

    fade_seconds = 0.02
    sample_count = int(sample_rate * TONE_DURATION_SECONDS)
    time_values = np.arange(sample_count, dtype=np.float32) / sample_rate
    envelope = np.minimum(time_values / fade_seconds, 1.0)
    envelope *= np.minimum(
        (TONE_DURATION_SECONDS - time_values) / fade_seconds, 1.0
    )
    silence = np.zeros(int(sample_rate * 0.04), dtype="<i2")
    tone_parts = []
    for index, frequency in enumerate(frequencies):
        tone_parts.append(
            (
                np.sin(2 * np.pi * frequency * time_values)
                * envelope
                * TONE_VOLUME
                * 32767
            ).astype("<i2")
        )
        if index + 1 < len(frequencies):
            tone_parts.append(silence)
    samples = np.concatenate(tone_parts)
    position = 0

    def play_callback(outdata, frames, time_info, status) -> None:
        nonlocal position
        del time_info, status
        count = min(frames, len(samples) - position)
        outdata.fill(0)
        if count:
            outdata[:count, 0] = samples[position : position + count]
            position += count
        if position >= len(samples):
            raise sd.CallbackStop

    with sd.OutputStream(
        device=output_device,
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        callback=play_callback,
    ) as stream:
        while stream.active:
            sd.sleep(10)


async def play_tone_sequence(
    sd, frequencies: tuple[int, ...], output_device: int, sample_rate: int
) -> None:
    try:
        await asyncio.to_thread(
            _play_tone_sequence, sd, frequencies, output_device, sample_rate
        )
    except sd.PortAudioError as exc:
        raise RuntimeError(f"Audio notification tone failed: {exc}") from exc


async def send_microphone_audio(
    session,
    audio_queue: asyncio.Queue[bytes | None],
    listening: threading.Event,
    types,
) -> None:
    while True:
        chunk = await audio_queue.get()
        if chunk is None:
            return
        if not listening.is_set():
            continue
        await session.send_realtime_input(
            audio=types.Blob(
                data=chunk,
                mime_type=f"audio/pcm;rate={INPUT_RATE}",
            )
        )


async def play_audio_stream(
    audio_queue: asyncio.Queue[bytes | object | None],
    turn_played: asyncio.Event,
) -> None:
    import sounddevice as sd

    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Audio playback needs numpy. Install it with "
            "`python -m pip install numpy` in the Python environment "
            "you use to run this script."
        ) from exc

    output_path = Path(__file__).resolve().parent / "gemini_voice_reply.wav"
    reply = None
    try:
        with sd.OutputStream(
            samplerate=OUTPUT_RATE, channels=1, dtype="int16"
        ) as stream:
            while True:
                audio = await audio_queue.get()
                if audio is None:
                    return
                if audio is END_TURN:
                    if reply is not None:
                        reply.close()
                        reply = None
                    turn_played.set()
                    continue

                if not isinstance(audio, bytes):
                    raise TypeError("Gemini returned audio in an unsupported format.")
                if reply is None:
                    reply = wave.open(str(output_path), "wb")
                    reply.setnchannels(1)
                    reply.setsampwidth(2)
                    reply.setframerate(OUTPUT_RATE)
                reply.writeframes(audio)
                await asyncio.to_thread(
                    stream.write, np.frombuffer(audio, dtype="<i2")
                )
    except sd.PortAudioError as exc:
        raise RuntimeError(f"Audio playback failed: {exc}") from exc
    finally:
        if reply is not None:
            reply.close()



async def wait_for_playback_turn(
    turn_played: asyncio.Event, playback_task: asyncio.Task[None]
) -> None:
    played_task = asyncio.create_task(turn_played.wait())
    completed, _ = await asyncio.wait(
        (played_task, playback_task),
        return_when=asyncio.FIRST_COMPLETED,
    )
    if playback_task in completed:
        played_task.cancel()
        playback_task.result()
        raise RuntimeError("Audio playback stopped before the reply finished.")
    await played_task


def select_microphone(sd, preferred_name: str = "oppo enco buds2"):
    try:
        devices = [
            device
            for device in sd.query_devices()
            if device["max_input_channels"] > 0
            and preferred_name in device["name"].lower()
        ]
    except sd.PortAudioError as exc:
        raise RuntimeError(f"Could not enumerate input microphones: {exc}") from exc

    if devices:
        host_apis = sd.query_hostapis()
        devices.sort(
            key=lambda device: (
                "wasapi" not in host_apis[device["hostapi"]]["name"].lower(),
                device["default_samplerate"] != INPUT_RATE,
                "@system32" in device["name"].lower(),
            )
        )
    else:
        host_apis = sd.query_hostapis()

    try:
        default_microphone = sd.query_devices(kind="input")
    except sd.PortAudioError as exc:
        raise RuntimeError(
            f"Could not find the system default microphone: {exc}"
        ) from exc
    if default_microphone["max_input_channels"] < 1:
        raise RuntimeError("The system default audio device has no input channels.")

    candidates = [(device, True) for device in devices]
    if all(
        device["index"] != default_microphone["index"]
        for device, _ in candidates
    ):
        candidates.append((default_microphone, False))

    def discard_input(indata, frames, time_info, status) -> None:
        del indata, frames, time_info, status

    for device, is_preferred in candidates:
        try:
            with sd.InputStream(
                device=device["index"],
                samplerate=INPUT_RATE,
                channels=1,
                dtype="int16",
                blocksize=int(INPUT_RATE * CHUNK_SECONDS),
                callback=discard_input,
            ):
                pass
        except sd.PortAudioError as exc:
            continue
        return device["index"], device["name"], is_preferred

    raise RuntimeError("Could not start an input microphone stream.")


def select_notification_output(
    sd,
) -> tuple[int, int]:
    try:
        default_device = sd.query_devices(kind="output")
    except sd.PortAudioError as exc:
        raise RuntimeError(f"Could not enumerate audio output devices: {exc}") from exc

    def silence_output(outdata, frames, time_info, status) -> None:
        del frames, time_info, status
        outdata.fill(0)

    sample_rate = int(default_device["default_samplerate"])
    try:
        with sd.OutputStream(
            device=default_device["index"],
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=max(1, int(sample_rate * CHUNK_SECONDS)),
            callback=silence_output,
        ):
            pass
    except sd.PortAudioError as exc:
        raise RuntimeError(
            f"Could not start the default audio output stream: {exc}"
        ) from exc
    return default_device["index"], sample_rate


def matched_wake_phrase(hypothesis: str) -> str | None:
    words = re.findall(r"[A-Z]+", hypothesis.upper())
    for start in range(len(words)):
        matches = [
            phrase
            for phrase in WAKE_WORDS
            if words[start : start + len(phrase.split())] == phrase.split()
        ]
        if matches:
            return max(matches, key=lambda phrase: len(phrase.split()))
    return None


def is_meaningful_transcript(text: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", text.casefold())
    normalized = " ".join(normalized.split())
    return bool(normalized) and normalized not in NON_SPEECH_TRANSCRIPTS


def normalize_voice_name(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    voice = value.strip().casefold()
    for supported_voice in LIVE_VOICES:
        if voice == supported_voice.casefold():
            return supported_voice
    choices = ", ".join(LIVE_VOICES)
    raise RuntimeError(f"GEMINI_VOICE must be one of: {choices}.")


def _is_speech_chunk(audio: bytes) -> bool:
    samples = memoryview(audio).cast("h")
    if not samples:
        return False
    peak = max(abs(sample) for sample in samples)
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    return peak >= 350 and rms >= 60


def capture_wake_continuation(
    audio_queue: queue.Queue[bytes],
) -> tuple[bytes, ...] | None:
    preroll: list[bytes] = []
    continuation: list[bytes] = []
    voice_started = False
    silent_chunks = 0
    chunks_without_voice = 0
    max_chunks_without_voice = math.ceil(
        WAKE_CONTINUATION_START_TIMEOUT_SECONDS / CHUNK_SECONDS
    )
    max_chunks = math.ceil(WAKE_CONTINUATION_MAX_SECONDS / CHUNK_SECONDS)

    for _ in range(max_chunks):
        try:
            audio = audio_queue.get(timeout=CHUNK_SECONDS)
        except queue.Empty:
            if not voice_started:
                chunks_without_voice += 1
                if chunks_without_voice >= max_chunks_without_voice:
                    break
            continue

        preroll.append(audio)
        if len(preroll) > WAKE_CONTINUATION_PREROLL_CHUNKS:
            preroll.pop(0)

        if _is_speech_chunk(audio):
            if not voice_started:
                continuation.extend(preroll)
                voice_started = True
            else:
                continuation.append(audio)
            silent_chunks = 0
        elif voice_started:
            continuation.append(audio)
            silent_chunks += 1
            if silent_chunks >= WAKE_CONTINUATION_SILENCE_CHUNKS:
                break
        else:
            chunks_without_voice += 1
            if chunks_without_voice >= max_chunks_without_voice:
                break

    return tuple(continuation) if voice_started else None


def wait_for_wake_phrase(
    sd,
    decoder_class,
    get_model_path,
    microphone_device: int,
    stop_event: threading.Event,
) -> tuple[bool, tuple[bytes, ...] | None] | None:
    audio_queue: queue.Queue[bytes] = queue.Queue()
    model_path = Path(get_model_path()) / "en-us"
    with tempfile.TemporaryDirectory(prefix="leela-wake-") as temp_dir:
        dictionary = Path(temp_dir) / "wake_words.dict"
        dictionary.write_text(
            "HII HH AY\n"
            "HI HH AY\n"
            "HEY HH EY\n"
            "LEELA L IY L AH\n"
            "LELA L IY L AH\n"
            "LILA L IY L AH\n",
            encoding="ascii",
        )
        keywords = Path(temp_dir) / "wake_words.kws"
        keywords.write_text(
            "".join(f"{phrase} /1e-20/\n" for phrase in WAKE_WORDS),
            encoding="ascii",
        )
        decoder = decoder_class(
            hmm=str(model_path / "en-us"),
            dict=str(dictionary),
            lm=None,
            samprate=INPUT_RATE,
            kws_threshold=1e-20,
        )
        decoder.add_kws(WAKE_SEARCH, str(keywords))
        decoder.activate_search(WAKE_SEARCH)
        decoder.start_utt()
        def capture_audio(indata, *callback_info) -> None:
            status = callback_info[-1]
            if status:
                print(f"Wake microphone warning: {status}", file=sys.stderr)
            audio_queue.put(bytes(indata))

        try:
            with sd.InputStream(
                device=microphone_device,
                samplerate=INPUT_RATE,
                channels=1,
                dtype="int16",
                blocksize=int(INPUT_RATE * CHUNK_SECONDS),
                callback=capture_audio,
            ):
                while not stop_event.is_set():
                    try:
                        audio = audio_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    decoder.process_raw(audio, False, False)
                    hypothesis = decoder.hyp()
                    if hypothesis is None or not hypothesis.hypstr:
                        continue
                    phrase = matched_wake_phrase(hypothesis.hypstr)
                    if phrase is not None:
                        continuation = capture_wake_continuation(audio_queue)
                        return True, continuation
        finally:
            decoder.end_utt()
    return None


async def listen_for_wake_phrase(
    sd, decoder_class, get_model_path, microphone_device: int
) -> tuple[bytes, ...] | None:
    stop_event = threading.Event()
    listener_task = asyncio.create_task(
        asyncio.to_thread(
            wait_for_wake_phrase,
            sd,
            decoder_class,
            get_model_path,
            microphone_device,
            stop_event,
        )
    )
    try:
        wake_result = await asyncio.shield(listener_task)
    except asyncio.CancelledError:
        stop_event.set()
        try:
            await asyncio.shield(listener_task)
        except Exception as exc:
            print(f"Wake listener shutdown failed: {exc!r}", file=sys.stderr)
        raise
    if wake_result is None:
        raise RuntimeError("Wake listener stopped unexpectedly.")
    return wake_result[1]


async def run_live_chat_session(
    client,
    config,
    types,
    sd,
    microphone_device: int,
    notification_device: int,
    notification_sample_rate: int,
    initial_audio: tuple[bytes, ...] | None = None,
    allow_barge_in: bool = False,
) -> None:
    loop = asyncio.get_running_loop()
    microphone_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    playback_queue: asyncio.Queue[bytes | object | None] = asyncio.Queue()
    turn_played = asyncio.Event()
    listening = threading.Event()
    blocksize = int(INPUT_RATE * CHUNK_SECONDS)
    last_stream_warning = [0.0]
    last_user_response_at = time.monotonic()
    receive_task: asyncio.Task | None = None
    turn_complete_received = False

    def capture_audio(indata, *callback_info) -> None:
        status = callback_info[-1]
        now = time.monotonic()
        if status and now - last_stream_warning[0] >= 5:
            print(f"Microphone stream warning: {status}", file=sys.stderr)
            last_stream_warning[0] = now
        if listening.is_set():
            loop.call_soon_threadsafe(
                microphone_queue.put_nowait, bytes(indata)
            )

    async with client.aio.live.connect(model=MODEL, config=config) as session:
        microphone_task = asyncio.create_task(
            send_microphone_audio(session, microphone_queue, listening, types)
        )
        playback_task = asyncio.create_task(
            play_audio_stream(playback_queue, turn_played)
        )
        try:
            with sd.InputStream(
                device=microphone_device,
                samplerate=INPUT_RATE,
                channels=1,
                dtype="int16",
                blocksize=blocksize,
                callback=capture_audio,
            ):
                await play_tone_sequence(
                    sd,
                    WAKE_TONE,
                    notification_device,
                    notification_sample_rate,
                )
                while not microphone_queue.empty():
                    microphone_queue.get_nowait()
                if initial_audio is not None:
                    for chunk in initial_audio:
                        microphone_queue.put_nowait(chunk)
                listening.set()
                print("Ready. Say something, or say 'bye' to sleep.")
                response_stream = session.receive().__aiter__()
                receive_task = asyncio.create_task(anext(response_stream))
                if initial_audio is None:
                    await session.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[types.Part(text="Hi")],
                        ),
                        turn_complete=True,
                    )
                input_transcript: list[str] = []
                while True:
                    remaining_idle = IDLE_SLEEP_SECONDS - (
                        time.monotonic() - last_user_response_at
                    )
                    completed, _ = await asyncio.wait(
                        (receive_task,),
                        timeout=max(remaining_idle, 0),
                    )
                    if not completed:
                        print(
                            "No user response for 2 minutes. Closing this chat "
                            "and returning to wake-word standby."
                        )
                        return

                    try:
                        response = receive_task.result()
                    except StopAsyncIteration:
                        if not turn_complete_received:
                            raise RuntimeError(
                                "Gemini Live response stream ended before "
                                "completing a turn."
                            )
                        response_stream = session.receive().__aiter__()
                        receive_task = asyncio.create_task(
                            anext(response_stream)
                        )
                        turn_complete_received = False
                        continue
                    receive_task = asyncio.create_task(
                        anext(response_stream)
                    )

                    if playback_task.done():
                        playback_task.result()

                    content = response.server_content
                    if content is None:
                        continue

                    if (
                        content.input_transcription
                        and content.input_transcription.text
                    ):
                        text = content.input_transcription.text
                        if is_meaningful_transcript(text):
                            input_transcript.append(text)
                            last_user_response_at = time.monotonic()
                            print(f"You: {text}")
                    if (
                        content.output_transcription
                        and content.output_transcription.text
                    ):
                        if not allow_barge_in:
                            listening.clear()
                        print(f"Gemini: {content.output_transcription.text}")

                    turn = content.model_turn
                    if turn is not None and turn.parts:
                        for part in turn.parts:
                            if part.inline_data and part.inline_data.data:
                                audio_data = part.inline_data.data
                                if not isinstance(audio_data, bytes):
                                    raise TypeError(
                                        "Gemini returned audio in an "
                                        "unsupported format."
                                    )
                                if not allow_barge_in:
                                    listening.clear()
                                playback_queue.put_nowait(audio_data)

                    if content.turn_complete:
                        turn_complete_received = True
                        playback_queue.put_nowait(END_TURN)
                        await wait_for_playback_turn(
                            turn_played, playback_task
                        )
                        turn_played.clear()
                        if re.search(
                            r"\b(?:good[- ]?)?bye\b",
                            " ".join(input_transcript),
                            re.IGNORECASE,
                        ):
                            print(
                                "You said bye. Closing this chat and "
                                "returning to wake-word standby."
                            )
                            return
                        input_transcript.clear()
                        while not microphone_queue.empty():
                            microphone_queue.get_nowait()
                        listening.set()
        finally:
            listening.clear()
            if receive_task is not None:
                receive_task.cancel()
            while not microphone_queue.empty():
                microphone_queue.get_nowait()
            microphone_queue.put_nowait(None)
            while not playback_queue.empty():
                playback_queue.get_nowait()
            playback_queue.put_nowait(None)
            microphone_task.cancel()
            playback_task.cancel()
            task_results = await asyncio.gather(
                microphone_task,
                playback_task,
                *([receive_task] if receive_task is not None else []),
                return_exceptions=True,
            )
            for task_result in task_results:
                if isinstance(task_result, StopAsyncIteration) and turn_complete_received:
                    continue
                if isinstance(task_result, BaseException) and not isinstance(
                    task_result, asyncio.CancelledError
                ):
                    print(
                        f"Voice task shutdown failed: {task_result!r}",
                        file=sys.stderr,
                    )


async def test_voice_chat(
    genai,
    types,
    voice_name: str | None = None,
    allow_barge_in: bool = False,
) -> None:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            "Microphone and speaker streaming needs sounddevice. Install it with "
            "`python -m pip install sounddevice` in the Python environment "
            "you use to run this script."
        ) from exc

    notification_device, notification_sample_rate = select_notification_output(sd)
    try:
        from pocketsphinx import Decoder, get_model_path
    except ImportError as exc:
        raise RuntimeError(
            "Offline wake-word detection needs PocketSphinx. Install it with "
            "`python -m pip install pocketsphinx`."
        ) from exc

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set GEMINI_API_KEY or GOOGLE_API_KEY in the environment or .env file."
        )

    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=(
            types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            )
            if voice_name
            else None
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                prefix_padding_ms=SPEECH_PREFIX_PADDING_MS,
                silence_duration_ms=END_OF_SPEECH_SILENCE_MS,
            ),
        ),
    )

    try:
        while True:
            microphone_device, microphone_name, preferred_microphone = (
                select_microphone(sd)
            )
            microphone_name = " ".join(microphone_name.split())
            microphone_status = (
                microphone_name
                if preferred_microphone
                else f"{microphone_name} (OPPO headset unavailable; using system default)"
            )
            print(f"Microphone: {microphone_status}.")
            print("Standby: say Leela to wake.")
            initial_audio = await listen_for_wake_phrase(
                sd, Decoder, get_model_path, microphone_device
            )
            await run_live_chat_session(
                client,
                config,
                types,
                sd,
                microphone_device,
                notification_device,
                notification_sample_rate,
                initial_audio,
                allow_barge_in,
            )
            await play_tone_sequence(
                sd, SLEEP_TONE, notification_device, notification_sample_rate
            )
    finally:
        await client.aio.aclose()


def main() -> int:
    try:
        parser = argparse.ArgumentParser(description="Gemini Live voice chat.")
        parser.add_argument(
            "--allow-barge-in",
            action="store_true",
            help="Allow microphone input while Gemini is speaking.",
        )
        args = parser.parse_args()

        try:
            from dotenv import load_dotenv
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Loading a .env file needs python-dotenv. Install it with "
                "`python -m pip install python-dotenv`."
            ) from exc

        env_file = Path(__file__).resolve().parent / ".env"
        load_dotenv(env_file)
        global MODEL
        MODEL = os.getenv("GEMINI_MODEL", MODEL)
        voice_name = normalize_voice_name(os.getenv("GEMINI_VOICE"))

        try:
            from google import genai
            from google.genai import types
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The Google GenAI SDK or one of its dependencies is missing. "
                "Install it with `python -m pip install google-genai`."
            ) from exc

        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            raise RuntimeError(
                "Set GEMINI_API_KEY or GOOGLE_API_KEY in the environment or .env file."
            )

        asyncio.run(
            test_voice_chat(
                genai, types, voice_name, allow_barge_in=args.allow_barge_in
            )
        )
    except KeyboardInterrupt:
        print("\nVoice chat stopped.")
        return 130
    except (RuntimeError, OSError, TimeoutError) as exc:
        print(
            f"Voice test failed ({type(exc).__name__}): {exc!r}",
            file=sys.stderr,
        )
        return 1

    print("Gemini Live voice chat ended.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
