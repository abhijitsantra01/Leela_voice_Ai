"""Local Gemini voice studio, with in-session voice/model reconfiguration."""
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from google import genai
from google.genai import types
from model_catalog import MODELS, BY_ID, VOICES, validate_settings, build_config

ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
MODEL=os.getenv('GEMINI_MODEL','gemini-2.5-flash-native-audio-preview-12-2025')
if MODEL not in BY_ID: MODEL=MODELS[0]['id']
app=FastAPI(title='Leela AI',docs_url=None,redoc_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','[::1]','testserver'])
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
active_sessions=set()

@app.get('/')
async def index(): return FileResponse(ROOT/'static/index.html',headers={'Cache-Control':'no-store'})
@app.get('/api/config')
async def config():
    voice=os.getenv('GEMINI_VOICE','Aoede')
    return {'configured':bool(os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')),
        'voice':voice if voice in VOICES else 'Aoede','voices':VOICES,'model':MODEL,'models':MODELS}
@app.get('/api/sample')
async def sample(): return FileResponse(ROOT/'gemini_voice_reply.wav',media_type='audio/wav')

def friendly_error(exc):
    code=str(getattr(exc,'code',''))
    message=str(exc).lower()
    if code=='429' or 'quota' in message or 'resource_exhausted' in message:
        return 'This model’s quota is exhausted. Choose another model or try later.'
    if code in ('401','403') or 'api key' in message:
        return 'Gemini rejected the credentials or access. Check your API key and model permissions.'
    if code=='404' or 'not found' in message or 'not supported' in message:
        return 'This model or configuration is unavailable for your account. Choose another model and try again.'
    return 'Gemini could not connect. Check model access, quota and internet, then try again.'

@app.websocket('/ws/live')
async def live(ws:WebSocket):
    origin=urlparse(ws.headers.get('origin',''))
    if origin.scheme not in ('http','https') or origin.netloc!=ws.headers.get('host'):
        await ws.close(code=1008); return
    await ws.accept()
    if active_sessions:
        await ws.send_json({'type':'error','message':'Another voice session is open. End it before starting here.'})
        await ws.close(code=1008); return
    active_sessions.add(ws)
    tasks=[]; client=None; history=[]
    try:
        key=os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        if not key:
            await ws.send_json({'type':'error','message':'Add GEMINI_API_KEY to .env and restart the server.'}); return
        settings=validate_settings(await asyncio.wait_for(ws.receive_json(),15),MODEL)
        client=genai.Client(api_key=key)
        revision=0
        while True:
            mode=BY_ID[settings['model']]['mode']
            # Each iteration fully closes the old upstream connection before starting the new one.
            async with client.aio.live.connect(model=settings['model'],config=build_config(settings,history)) as session:
                await ws.send_json({'type':'ready','settings':settings,'mode':mode,'revision':revision})
                last_activity=time.monotonic()
                pending={'user':'','assistant':''}
                def commit():
                    for role,text in pending.items():
                        if text.strip(): history.append({'role':role,'text':text[-6000:]})
                        pending[role]=''
                    del history[:-40]
                async def upstream():
                    nonlocal last_activity
                    while True:
                        message=await ws.receive()
                        if message['type']=='websocket.disconnect': return None
                        audio=message.get('bytes')
                        if audio is not None:
                            if len(audio)>32768 or len(audio)%2: raise ValueError('Invalid audio frame.')
                            await session.send_realtime_input(audio=types.Blob(data=audio,mime_type='audio/pcm;rate=16000'))
                        elif message.get('text'):
                            data=json.loads(message['text'])
                            action=data.get('type')
                            if action=='stop': return None
                            if action=='reconfigure':
                                try: return validate_settings(data,MODEL)
                                except ValueError as exc:
                                    await ws.send_json({'type':'settings_error','message':str(exc),'settings':settings})
                            elif action=='mute': await session.send_realtime_input(audio_stream_end=True)
                            elif action=='text':
                                if mode!='chat':
                                    await ws.send_json({'type':'notice','message':'This model takes microphone audio only.'}); continue
                                text=str(data.get('text','')).strip()[:2000]
                                if text:
                                    last_activity=time.monotonic(); commit()
                                    history.append({'role':'user','text':text}); del history[:-40]
                                    await session.send_client_content(turns=types.Content(role='user',parts=[types.Part(text=text)]),turn_complete=True)
                async def downstream():
                    nonlocal last_activity
                    while True:
                        async for response in session.receive():
                            content=response.server_content
                            status=getattr(content,'interaction_status',None) or getattr(response,'interaction_status',None)
                            if status: await ws.send_json({'type':'interaction','status':getattr(status,'value',str(status))})
                            if not content: continue
                            if content.interrupted:
                                commit(); await ws.send_json({'type':'interrupted'})
                            interim=getattr(content,'interim_input_transcription',None)
                            if interim and interim.text:
                                last_activity=time.monotonic()
                                await ws.send_json({'type':'interim','text':interim.text})
                            for field,role in [('input_transcription','user'),('output_transcription','assistant')]:
                                transcript=getattr(content,field,None)
                                if transcript and transcript.text:
                                    if role=='user': last_activity=time.monotonic()
                                    pending[role]+=transcript.text
                                    final=mode=='transcribe' or bool(getattr(transcript,'finished',False))
                                    await ws.send_json({'type':'transcript','role':role,'text':transcript.text,'final':final})
                                    if mode=='transcribe': commit()
                            if content.model_turn:
                                for part in content.model_turn.parts or []:
                                    if part.inline_data and part.inline_data.data: await ws.send_bytes(part.inline_data.data)
                            if content.turn_complete:
                                commit(); await ws.send_json({'type':'turn_complete'})
                async def idle_guard():
                    while True:
                        await asyncio.sleep(5)
                        if time.monotonic()-last_activity>120:
                            await ws.send_json({'type':'ended','message':'Paused after two quiet minutes. Start again when you’re ready.'}); return None
                tasks=[asyncio.create_task(fn()) for fn in (upstream,downstream,idle_guard)]
                try:
                    done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                    new_settings=None
                    for task in done:
                        result=task.result()
                        if task is tasks[0]: new_settings=result
                finally:
                    for task in tasks: task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
                    tasks=[]
                commit()
            if new_settings is None: break
            settings=new_settings; revision+=1
            await ws.send_json({'type':'switching'})
    except WebSocketDisconnect: pass
    except Exception as exc:
        logging.warning('Live session failed (%s)',type(exc).__name__)
        try: await ws.send_json({'type':'error','message':str(exc) if isinstance(exc,ValueError) else friendly_error(exc)})
        except Exception: pass
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        if client:
            try: await client.aio.aclose()
            except Exception: logging.warning('Client cleanup failed')
        active_sessions.discard(ws)
        try:
            await ws.close()
        except (WebSocketDisconnect, RuntimeError):
            pass

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8000,ws_max_size=65536)
