'use strict';
const $=id=>document.getElementById(id);
const VOICES={Aoede:{mood:'Breezy & light',color:'sky blue',hello:'A breath of fresh conversation.'},Kore:{mood:'Calm & grounded',color:'soft lavender',hello:'A little clarity. A little calm.'},Puck:{mood:'Warm & upbeat',color:'fresh mint',hello:'A little spark for your day.'},Charon:{mood:'Clear & thoughtful',color:'warm sand',hello:'Make room for a new perspective.'},Fenrir:{mood:'Bright & expressive',color:'soft peach',hello:'Let’s see where this takes us.'}};
let desired={voice:'Aoede',language:'Auto',model:''},active=null,config=null;
let socket,stream,context,recorder,source,silentGain,outputGain;
let ready=false,starting=false,switching=false,stopping=false,muted=false,token=0,timer,timeout;
let startTime=0,nextPlay=0,sources=new Set(),rows=[],currentRows={},level=0,receiveComplete=true,reasoning=false,following=true;
const sample=$('sampleAudio'),motionQuery=matchMedia('(prefers-reduced-motion: reduce)');
const waveBars=Array.from({length:33},()=>{const b=document.createElement('span');$('wave').append(b);return b;});
const modelInfo=(settings=desired)=>config?.models.find(m=>m.id===settings?.model);
const mode=(settings=active||desired)=>modelInfo(settings)?.mode||'chat';
const sameSettings=(a,b)=>a&&b&&a.voice===b.voice&&a.language===b.language&&a.model===b.model;
function notice(message=''){$('notice').textContent=message;$('notice').hidden=!message;}
function setState(state,message){
 document.body.dataset.state=state;$('status').textContent=message;
 const m=mode(),voice=VOICES[desired.voice];
 const titles={idle:m==='translate'?'A bridge between languages.':m==='transcribe'?'Your words, beautifully captured.':voice.hello,connecting:'Making a connection.',switching:'A fresh voice, the same conversation.',listening:m==='translate'?'Speak. I’ll translate.':m==='transcribe'?'Listening, word by word.':'I’m all ears.',speaking:m==='translate'?'In other words…':'A thought for you.',muted:'Take your time.',thinking:'Let me think with you.'};
 $('sessionTitle').textContent=titles[state]||voice.hello;
 const hints={idle:m==='chat'?"I'm Leela. What's on your mind today?":m==='translate'?'Choose a target language and start speaking.':'Press start and see your speech turn into live notes.',connecting:'Your space is almost ready.',switching:'Applying your selection. Your notes stay right here.',listening:m==='chat'?'An idea, a question, or just a hello.':m==='translate'?'Headphones help keep translated audio out of the microphone.':'Speak naturally. No spoken AI reply in this mode.',speaking:m==='translate'?'Live interpretation in your chosen language.':$('bargeIn').checked?'You can jump in whenever you like.':'I’ll listen again as soon as this thought is finished.',muted:'Your microphone is off. Unmute when you’re ready.',thinking:'Making a little room for a good answer.'};
 $('sessionHint').textContent=hints[state]||'';
}
function restingState(){if(sources.size)return;setState(muted?'muted':reasoning||!receiveComplete?'thinking':'listening',muted?'Microphone muted':reasoning||!receiveComplete?'Thinking with you':'Listening to you');}
function renderSelection(){
 const v=VOICES[desired.voice],m=mode(desired);document.body.dataset.voice=desired.voice;
 document.querySelectorAll('.voice-option').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.voice===desired.voice));b.disabled=m!=='chat';});
 $('voiceMood').textContent=m==='chat'?`${desired.voice.toUpperCase()} · ${v.mood.toUpperCase()}`:m==='translate'?'LIVE INTERPRETATION':'LIVE TRANSCRIPTION';
 $('activeVoice').textContent=m==='chat'?`${desired.voice}'s voice · ${v.color} mood`:m==='translate'?'Translation voice is managed by the model':'Transcription · no audio reply';
 $('voiceHelp').textContent=m==='chat'?'Five voices. Your kind of energy.':'Companion voices are available in conversation mode.';
 $('modelSelect').value=desired.model;$('languageSelect').value=desired.language;
 $('languageLabel').textContent=m==='translate'?'TRANSLATE INTO':'CONVERSATION LANGUAGE';
 $('languageSelect').options[0].disabled=m==='translate';
 $('modelDescription').textContent=modelInfo(desired)?.description||'';
 $('modeNote').textContent=m==='chat'?'Switch voices anytime. Recent conversation context stays with you.':m==='translate'?'Audio in. Translated speech out. Choose your target language.':'Speech in. Live notes out. No voice reply in this mode.';
 $('modeBadge').textContent={chat:'VOICE + TEXT',translate:'LIVE TRANSLATION',transcribe:'LIVE CAPTIONS'}[m];
 $('chatSubtitle').textContent={chat:'A place for every thought.',translate:'Your words, in another language.',transcribe:'Every word, a little clearer.'}[m];
 document.querySelectorAll('[data-prompt]').forEach(b=>b.disabled=m!=='chat'||starting||switching);
 $('textInput').placeholder=m==='chat'?"Or type what's on your mind…":'This mode listens to your microphone';
 updateControls();if(!ready&&!starting&&!switching)setState('idle','Ready when you are');
}
function updateControls(){
 $('muteButton').disabled=!ready;
 $('textInput').disabled=$('sendButton').disabled=!ready||mode()!=='chat';
 $('startButton').disabled=stopping;
 $('startLabel').textContent=stopping?'Ending…':starting?'Cancel connection':ready||switching?'End session':mode(desired)==='chat'?"Let's talk":mode(desired)==='translate'?'Start translating':'Start captions';
}
function scrollLatest(){following=true;$('transcript').scrollTop=$('transcript').scrollHeight;$('latestButton').hidden=true;}
$('transcript').addEventListener('scroll',()=>{const el=$('transcript');following=el.scrollHeight-el.scrollTop-el.clientHeight<55;if(following)$('latestButton').hidden=true;});
$('latestButton').onclick=scrollLatest;
function addTranscript(role,text,{standalone=false,final=false}={}){
 if(!text)return;$('emptyState')?.remove();
 if(!currentRows[role]||standalone){
  const el=document.createElement('div');el.className='message '+role;
  const label=document.createElement('div');label.className='message-label';
  const name=role==='user'?'You':mode()==='translate'?'Translation':`Leela · ${active?.voice||desired.voice}`;
  label.textContent=name;const p=document.createElement('p');el.append(label,p);$('transcript').append(el);
  const row={role,name,text:'',p};rows.push(row);currentRows[role]=row;
 }
 const row=currentRows[role];row.text+=text;row.p.textContent=row.text;
 if(following)scrollLatest();else $('latestButton').hidden=false;
 $('exportButton').disabled=false;
 if(standalone||final)delete currentRows[role];
}
function clearPlayback(){for(const node of sources){node.onended=null;try{node.stop();}catch{}}sources.clear();nextPlay=0;}
function playPCM(data){
 if(!context||!ready||data.byteLength%2)return;
 const samples=new DataView(data),buffer=context.createBuffer(1,data.byteLength/2,24000),out=buffer.getChannelData(0);
 for(let i=0;i<out.length;i++)out[i]=samples.getInt16(i*2,true)/32768;
 const first=!sources.size,node=context.createBufferSource();node.buffer=buffer;node.connect(outputGain);sources.add(node);
 nextPlay=Math.max(context.currentTime+.025,nextPlay);node.start(nextPlay);nextPlay+=buffer.duration;
 if(first&&!$('bargeIn').checked&&mode()==='chat')send({type:'mute'});
 setState('speaking',mode()==='translate'?'Translating your words':`${active.voice} is speaking`);
 node.onended=()=>{sources.delete(node);if(!sources.size&&ready)restingState();};
}
function send(data){if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify(data));}
function armTimeout(){clearTimeout(timeout);const generation=token;timeout=setTimeout(()=>{if(generation===token&&(starting||switching)){notice('The connection took too long. Check your connection and model access, then try again.');void endSession();}},25000);}
function requestSwitch(){
 if(!ready||switching||sameSettings(desired,active))return;
 ready=false;switching=true;clearPlayback();currentRows={};$('interim').hidden=true;
 setState('switching','Applying your selection');updateControls();armTimeout();
 send({type:'reconfigure',...desired});
}
function changeSelection(patch){
 desired={...desired,...patch};if(mode(desired)==='translate'&&desired.language==='Auto')desired.language='English';
 renderSelection();requestSwitch();
}
async function endSession(){
 if(stopping)return;stopping=true;token++;ready=starting=switching=false;
 clearTimeout(timeout);clearInterval(timer);const oldSocket=socket;socket=null;
 if(oldSocket&&oldSocket.readyState<2)oldSocket.close();
 recorder?.disconnect();source?.disconnect();silentGain?.disconnect();recorder=source=silentGain=null;
 stream?.getTracks().forEach(t=>t.stop());stream=null;clearPlayback();
 const oldContext=context;context=null;outputGain=null;muted=false;active=null;reasoning=false;currentRows={};$('interim').hidden=true;
 $('muteButton').setAttribute('aria-pressed','false');$('muteButton').setAttribute('aria-label','Mute microphone');updateControls();
 if(oldContext&&oldContext.state!=='closed')await oldContext.close().catch(()=>{});
 stopping=false;renderSelection();
}
function onServerMessage(event,generation,prompt){
 if(generation!==token)return;
 if(event.data instanceof ArrayBuffer){if(ready){receiveComplete=false;playPCM(event.data);}return;}
 const msg=JSON.parse(event.data);
 if(msg.type==='ready'){
  clearTimeout(timeout);active=msg.settings;ready=true;starting=switching=false;receiveComplete=true;reasoning=false;
  // Rapid selections are serialized: wait for one ready acknowledgement, then apply the latest choice.
  if(!sameSettings(desired,active)){requestSwitch();return;}
  if(!startTime){startTime=Date.now();timer=setInterval(()=>{const n=Math.floor((Date.now()-startTime)/1000);$('timer').textContent=`${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;},1000);}
  renderSelection();restingState();
  if(msg.revision>0)notice(mode()==='chat'?`${active.voice} is ready. Your recent conversation context is carried over.`:'Your selected mode is ready.');
  if(prompt&&msg.revision===0&&mode()==='chat')sendText(prompt);
 }else if(msg.type==='error'||msg.type==='ended'){notice(msg.message);void endSession();}
 else if(msg.type==='settings_error'){clearTimeout(timeout);desired=msg.settings;active=msg.settings;switching=false;ready=true;renderSelection();restingState();notice(msg.message);}
 else if(msg.type==='notice'){notice(msg.message);}
 else if(ready){
  if(msg.type==='transcript'){if(msg.role==='user')$('interim').hidden=true;addTranscript(msg.role,msg.text,{final:msg.final});}
  else if(msg.type==='interim'){$('interim').textContent=msg.text;$('interim').hidden=false;}
  else if(msg.type==='interrupted'){clearPlayback();currentRows={};receiveComplete=true;reasoning=false;restingState();}
  else if(msg.type==='interaction'){reasoning=msg.status==='IN_PROGRESS';if(!reasoning)receiveComplete=true;restingState();}
  else if(msg.type==='turn_complete'){currentRows={};receiveComplete=true;restingState();}
 }
}
async function startSession(prompt=''){
 if(ready||starting||switching||stopping)return;
 if(!config?.configured){notice('Add GEMINI_API_KEY to .env, restart python app.py, and reload this page. You can play the supplied sample meanwhile.');return;}
 if(!navigator.mediaDevices?.getUserMedia||!window.AudioWorkletNode){notice('Open http://localhost:8000 in Chrome or Edge. Voice capture needs localhost or HTTPS.');return;}
 pauseSample();notice();starting=true;const generation=++token;startTime=0;$('timer').textContent='00:00';
 setState('connecting','Connecting to Leela');updateControls();
 try{
  const ctx=new AudioContext({sampleRate:16000});context=ctx;await ctx.resume();
  if(generation!==token)return;
  if(ctx.sampleRate!==16000)throw new Error('This browser cannot capture 16 kHz audio. Try Chrome or Edge.');
  const captured=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
  if(generation!==token){captured.getTracks().forEach(t=>t.stop());return;}stream=captured;
  await ctx.audioWorklet.addModule('/static/pcm-worklet.js');if(generation!==token)return;
  source=ctx.createMediaStreamSource(stream);recorder=new AudioWorkletNode(ctx,'pcm-processor');silentGain=ctx.createGain();silentGain.gain.value=0;
  outputGain=ctx.createGain();outputGain.gain.value=Number($('volume').value)/100;outputGain.connect(ctx.destination);
  source.connect(recorder);recorder.connect(silentGain);silentGain.connect(ctx.destination);
  recorder.port.onmessage=({data})=>{
   if(data.level!==undefined)level=data.level;
   const canSend=mode()!=='chat'||!sources.size||$('bargeIn').checked;
   if(data.audio&&ready&&!muted&&canSend&&socket?.readyState===1){
    if(socket.bufferedAmount>128000){notice('Connection is falling behind. The session stopped; try again.');void endSession();return;}
    socket.send(data.audio);
   }
  };
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/live`);socket=ws;ws.binaryType='arraybuffer';armTimeout();
  ws.onopen=()=>{if(generation===token)ws.send(JSON.stringify(desired));};
  ws.onmessage=e=>onServerMessage(e,generation,prompt);
  ws.onerror=()=>{if(generation===token)notice('Cannot reach the voice server. Check that python app.py is running.');};
  ws.onclose=()=>{if(generation===token){notice('The connection closed. Start again to reconnect.');void endSession();}};
 }catch(error){if(generation!==token)return;notice(error.name==='NotAllowedError'?'Allow microphone access in your browser and try again.':error.name==='NotFoundError'?'No microphone found. Connect one and try again.':error.message||'Could not start audio.');await endSession();}
}
function sendText(text){text=text.trim();if(!text||!ready||mode()!=='chat')return;currentRows={};addTranscript('user',text,{standalone:true});send({type:'text',text});$('textInput').value='';receiveComplete=false;restingState();}
$('startButton').onclick=()=>{if(ready||starting||switching)void endSession();else void startSession();};
$('muteButton').onclick=()=>{if(!ready)return;muted=!muted;stream?.getAudioTracks().forEach(t=>t.enabled=!muted);$('muteButton').setAttribute('aria-pressed',String(muted));$('muteButton').setAttribute('aria-label',muted?'Unmute microphone':'Mute microphone');if(muted)send({type:'mute'});restingState();};
$('textForm').onsubmit=e=>{e.preventDefault();sendText($('textInput').value);};
document.querySelectorAll('.voice-option').forEach(b=>b.onclick=()=>changeSelection({voice:b.dataset.voice}));
$('modelSelect').onchange=()=>changeSelection({model:$('modelSelect').value});
$('languageSelect').onchange=()=>changeSelection({language:$('languageSelect').value});
$('settingsButton').onclick=()=>$('settingsDialog').showModal();$('aboutButton').onclick=()=>$('aboutDialog').showModal();
$('reduceMotion').onchange=()=>document.body.classList.toggle('quiet',$('reduceMotion').checked);
$('volume').oninput=()=>{const volume=Number($('volume').value)/100;$('volumeValue').textContent=$('volume').value+'%';if(outputGain)outputGain.gain.setTargetAtTime(volume,context.currentTime,.02);sample.volume=volume;};
function pauseSample(){sample.pause();sample.currentTime=0;$('sampleButton').setAttribute('aria-label','Play supplied recording');$('sampleButton').setAttribute('aria-pressed','false');if(!ready&&!starting&&!switching)setState('idle','Ready when you are');}
$('sampleButton').onclick=async()=>{if(ready||starting||switching){notice('End your live session before playing the sample.');return;}if(!sample.paused){pauseSample();return;}notice('Playing your supplied recording — this is not a preview of the selected voice.');try{sample.volume=Number($('volume').value)/100;await sample.play();$('sampleButton').setAttribute('aria-label','Pause recording');$('sampleButton').setAttribute('aria-pressed','true');setState('speaking','Playing your recording');}catch{notice('The sample could not play.');}};
sample.onended=pauseSample;
$('exportButton').onclick=()=>{const text=rows.map(r=>`${r.name}: ${r.text}`).join('\n\n');const url=URL.createObjectURL(new Blob(['Leela AI — conversation notes\n\n'+text],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='Leela_conversation.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{if(mode(desired)!=='chat')return;if(ready)sendText(b.dataset.prompt);else void startSession(b.dataset.prompt);});
window.addEventListener('pagehide',()=>{stream?.getTracks().forEach(t=>t.stop());socket?.close();context?.close();});
let lastFrame=0;function animate(t){if(t-lastFrame>65){lastFrame=t;const quiet=$('reduceMotion').checked||motionQuery.matches;const speaking=document.body.dataset.state==='speaking';const amp=quiet?0:speaking ? 0.65 : ready&&!muted?Math.min(1,level*9):0;waveBars.forEach((b,i)=>{b.style.height=(4+amp*23*Math.abs(Math.sin(t/200+i*.72))*Math.sin((i+1)/34*Math.PI))+'px';});}requestAnimationFrame(animate);}requestAnimationFrame(animate);
fetch('/api/config').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>{
 config=data;desired={voice:data.voice,model:data.model,language:'Auto'};$('modelSelect').replaceChildren();
 for(const model of data.models){const option=document.createElement('option');option.value=model.id;option.textContent=model.name;$('modelSelect').append(option);}
 $('modelSelect').disabled=false;renderSelection();if(!data.configured)notice('Your studio is ready. Add your Gemini API key to .env to start a live conversation.');
}).catch(()=>notice('Could not load settings. Start python app.py and open http://localhost:8000.'));
