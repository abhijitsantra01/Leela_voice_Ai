"""Offline HTTP, model configuration, streaming and reconnect regression checks."""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import app as web
from model_catalog import MODELS, BY_ID, validate_settings, build_config

class FakeSession:
    def __init__(self):
        self.audio=[]; self.text=[]; self.trigger=asyncio.Event(); self.closed=False
    async def send_realtime_input(self,**kwargs): self.audio.append(kwargs)
    async def send_client_content(self,**kwargs): self.text.append(kwargs); self.trigger.set()
    async def receive(self):
        await self.trigger.wait(); self.trigger.clear()
        yield NS(server_content=NS(interrupted=False,input_transcription=NS(text='Hello'),output_transcription=NS(text='Hi there.'),model_turn=NS(parts=[NS(inline_data=NS(data=b'\x00\x01'*240))]),turn_complete=True))
class FakeConnection:
    def __init__(self,session): self.session=session
    async def __aenter__(self): return self.session
    async def __aexit__(self,*args): self.session.closed=True

class AppTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(web.app)
        self.env=patch.dict(os.environ,{'GEMINI_API_KEY':'','GOOGLE_API_KEY':''}); self.env.start()
    def tearDown(self): self.env.stop()
    def test_assets_and_secret_isolation(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.get('/static/app.js').status_code,200)
        self.assertEqual(self.client.get('/api/sample').content[:4],b'RIFF')
        self.assertEqual(self.client.get('/.env').status_code,404)
        cfg=self.client.get('/api/config').json()
        self.assertFalse(cfg['configured']); self.assertEqual(len(cfg['models']),6)
    def test_cross_origin_rejected(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws/live',headers={'origin':'http://evil.invalid'}): pass
    def test_missing_key(self):
        with self.client.websocket_connect('/ws/live',headers={'origin':'http://testserver'}) as ws:
            self.assertIn('.env',ws.receive_json()['message'])
    def test_model_specific_configs(self):
        for m in MODELS:
            settings=validate_settings({'model':m['id'],'voice':'Aoede','language':'Bengali'},web.MODEL)
            cfg=build_config(settings,[])
            if m['mode']=='translate':
                self.assertEqual(cfg.translation_config.target_language_code,'bn')
                self.assertIsNone(cfg.system_instruction); self.assertIsNone(cfg.speech_config)
            elif m['mode']=='transcribe':
                self.assertEqual(cfg.response_modalities,['TEXT'])
                self.assertEqual(cfg.input_audio_transcription.language_codes,['bn'])
                self.assertIsNone(cfg.speech_config)
            else:
                self.assertEqual(cfg.speech_config.voice_config.prebuilt_voice_config.voice_name,'Aoede')
        default=build_config({'model':'gemini-3.8-live','voice':'Kore','language':'Auto'},[])
        self.assertIsNone(default.thinking_config)
        extended=build_config({'model':'gemini-3.8-live-extended-thinking','voice':'Kore','language':'Auto'},[])
        self.assertIsNotNone(extended.thinking_config)
    def test_invalid_model_and_translation_target(self):
        with self.assertRaises(ValueError): validate_settings({'model':'invented-model'},web.MODEL)
        with self.assertRaises(ValueError): validate_settings({'model':MODELS[2]['id'],'language':'Auto'},web.MODEL)
    def test_live_switch_closes_old_session_and_preserves_context(self):
        sessions=[]; configs=[]; closed=[]
        def connect(**kwargs):
            if sessions: self.assertTrue(sessions[-1].closed,'Old upstream connection must close first')
            configs.append(kwargs); s=FakeSession(); sessions.append(s); return FakeConnection(s)
        async def aclose(): closed.append(True)
        fake=NS(aio=NS(live=NS(connect=connect),aclose=aclose))
        with patch.dict(os.environ,{'GEMINI_API_KEY':'fake-test-key'}),patch.object(web.genai,'Client',return_value=fake):
            with self.client.websocket_connect('/ws/live',headers={'origin':'http://testserver'}) as ws:
                ws.send_json({'voice':'Kore','language':'Auto','model':MODELS[0]['id']})
                self.assertEqual(ws.receive_json()['revision'],0)
                ws.send_bytes(b'\x01\x00'*1600); ws.send_json({'type':'text','text':'I am learning Python.'})
                self.assertEqual(ws.receive_json()['role'],'user')
                self.assertEqual(ws.receive_json()['text'],'Hi there.')
                self.assertEqual(ws.receive_bytes(),b'\x00\x01'*240)
                self.assertEqual(ws.receive_json()['type'],'turn_complete')
                ws.send_json({'type':'reconfigure','voice':'Aoede','model':'gemini-3.8-live','language':'Bengali'})
                self.assertEqual(ws.receive_json()['type'],'switching')
                ready=ws.receive_json(); self.assertEqual(ready['settings']['voice'],'Aoede'); self.assertEqual(ready['revision'],1)
                self.assertIn('learning Python',configs[1]['config'].system_instruction)
                self.assertEqual(configs[1]['config'].speech_config.voice_config.prebuilt_voice_config.voice_name,'Aoede')
                ws.send_bytes(b'\x01\x00'*1600)
                # Invalid switch must keep the current connection usable.
                ws.send_json({'type':'reconfigure','model':'invalid'})
                self.assertEqual(ws.receive_json()['type'],'settings_error')
                ws.send_json({'type':'stop'})
            self.assertEqual(len(sessions),2); self.assertTrue(closed); self.assertFalse(web.active_sessions)
            self.assertEqual(len(sessions[1].audio),1)
    def test_special_modes_reject_typed_messages(self):
        for model in (MODELS[2],MODELS[3]):
            s=FakeSession()
            async def aclose(): pass
            fake=NS(aio=NS(live=NS(connect=lambda **kw:FakeConnection(s)),aclose=aclose))
            with patch.dict(os.environ,{'GEMINI_API_KEY':'fake-test-key'}),patch.object(web.genai,'Client',return_value=fake):
                with self.client.websocket_connect('/ws/live',headers={'origin':'http://testserver'}) as ws:
                    ws.send_json({'model':model['id'],'language':'English'})
                    self.assertEqual(ws.receive_json()['mode'],model['mode'])
                    ws.send_json({'type':'text','text':'hello'})
                    self.assertEqual(ws.receive_json()['type'],'notice'); ws.send_json({'type':'stop'})
                self.assertFalse(s.text)
    def test_errors_do_not_echo_provider_secrets(self):
        self.assertNotIn('test-secret',web.friendly_error(RuntimeError('test-secret provider details')))
        self.assertIn('quota',web.friendly_error(RuntimeError('quota exceeded')))

if __name__=='__main__': unittest.main()
