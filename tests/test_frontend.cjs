// State-machine regression tests in Node; no simulated claims about browser visual QA.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(){this.dataset={};this.style={};this.attrs={};this.children=[];this.options=[{}];this.value='';this.disabled=false;this.hidden=false;this.checked=false;this.scrollHeight=500;this.scrollTop=0;this.clientHeight=300;}
 append(...items){this.children.push(...items);}setAttribute(k,v){this.attrs[k]=v;}addEventListener(){}replaceChildren(){this.children=[];}remove(){}showModal(){}click(){}
}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
get('sampleAudio').pause=()=>{};get('sampleAudio').paused=true;get('volume').value='85';
const voices=['Aoede','Kore','Puck','Charon','Fenrir'].map(voice=>Object.assign(new Element(),{dataset:{voice}}));
const sandbox={console,document:{getElementById:get,createElement:()=>new Element(),querySelectorAll:selector=>selector==='.voice-option'?voices:[],body:{dataset:{},classList:{toggle(){}}}},window:{addEventListener(){}},matchMedia:()=>({matches:false}),requestAnimationFrame(){},fetch:()=>new Promise(()=>{}),setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},WebSocket:{OPEN:1},ArrayBuffer,Date,Blob,URL};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8'),sandbox);
const run=code=>vm.runInContext(code,sandbox);
run(`config={models:[{id:'chat',mode:'chat'},{id:'translation',mode:'translate'},{id:'captions',mode:'transcribe'}]};desired={voice:'Kore',language:'Auto',model:'chat'};active={...desired};ready=true;socket={readyState:1,sent:[],send(v){this.sent.push(JSON.parse(v));}};`);
run(`changeSelection({voice:'Aoede'});`);
assert.equal(run('socket.sent[0].type'),'reconfigure');assert.equal(run('socket.sent[0].voice'),'Aoede');assert.equal(run('ready'),false);assert.equal(run('switching'),true);
run(`changeSelection({voice:'Puck'});`);assert.equal(run('socket.sent.length'),1,'Do not overlap reconfigurations');
run(`onServerMessage({data:JSON.stringify({type:'ready',settings:{voice:'Aoede',model:'chat',language:'Auto'},revision:1})},token,'');`);
assert.equal(run('socket.sent.length'),2);assert.equal(run('socket.sent[1].voice'),'Puck');
run(`muted=true;onServerMessage({data:JSON.stringify({type:'ready',settings:{voice:'Puck',model:'chat',language:'Auto'},revision:2})},token,'');`);
assert.equal(run('ready'),true);assert.equal(run('muted'),true,'Switch must retain mute');assert.equal(sandbox.document.body.dataset.state,'muted');
run(`changeSelection({model:'translation'});`);assert.equal(run('desired.language'),'English');assert.ok(voices.every(b=>b.disabled));
run(`onServerMessage({data:JSON.stringify({type:'ready',settings:{...desired},revision:3})},token,'');`);
assert.equal(get('textInput').disabled,true,'No text prompts in translation mode');
run(`following=false;addTranscript('user','Read this',{standalone:true});`);assert.equal(get('latestButton').hidden,false,'Do not force the reader to the bottom');
run(`scrollLatest();`);assert.equal(get('latestButton').hidden,true);
run(`reasoning=true;receiveComplete=false;onServerMessage({data:JSON.stringify({type:'turn_complete'})},token,'');`);assert.equal(sandbox.document.body.dataset.state,'muted');
run(`muted=false;restingState();`);assert.equal(sandbox.document.body.dataset.state,'thinking','Extended reasoning must outlive an utterance');
console.log('Frontend regression checks passed: voice switching, rapid selection, mute retention, mode controls, scroll following, reasoning state.');
