const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
class Element {
  constructor() { this.attrs = {}; this.dataset = {}; this.style = {setProperty(){}}; this.children = []; this.hidden = false; this.classList = {toggle:(key,on)=>{this.attrs[key]=on}}; this.textContent=''; }
  setAttribute(key,value){this.attrs[key]=value;if(key==='hidden')this.hidden=true}
  removeAttribute(key){delete this.attrs[key];if(key==='hidden')this.hidden=false}
  addEventListener(){}
  append(...items){this.children.push(...items)}
  replaceChildren(...items){this.children=items}
  closest(){return this}
  focus(){this.focused=true}
}
const elements = Object.fromEntries([...fs.readFileSync(__dirname+'/../static/index.html','utf8').matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
elements['cover'].setAttribute('hidden','');
const document={body:new Element(),getElementById:id=>{assert(elements[id],`Unknown DOM id ${id}`);return elements[id]},createElement:()=>new Element(),addEventListener(){},hidden:false};
const context=vm.createContext({document,console,URL,Date,AbortController,setTimeout:()=>0,clearTimeout(){},setInterval(){},fetch:async()=>({ok:false})});
vm.runInContext(fs.readFileSync(__dirname+'/../static/app.js','utf8'),context);
const base={source:'vinyl',disc:{present:false,tracks:[]},player:{state:'stop'},vinyl:{connected:true,available:true,state:'idle',message:'Klaar',history:[]}};
const render=data=>vm.runInContext('state='+JSON.stringify(data)+';render()',context);
render(base);
assert.equal(elements['vinyl-panel'].hidden,false);
assert.equal(elements['spotify-connect'].hidden,true);
assert.equal(elements['playback-controls'].hidden,true);
assert.equal(elements['source-vinyl'].attrs['aria-pressed'],'true');
assert.equal(elements['source-spotify'].attrs['aria-pressed'],'false');
for (const phase of ['idle','listening','recognizing','no_match','silent','error']) {
 render({...base,vinyl:{...base.vinyl,automatic:true,state:phase,message:'Geen match, technisch detail'}});
 assert.equal(elements['album-name'].textContent,'Vinyl');
 assert.equal(elements['artist'].textContent,'Laat de plaat maar draaien.');
 assert.equal(elements['cover'].hidden,true);
 assert.equal(elements['metadata-status'].hidden,true);
}
const track={title:'Song <script>',artist:'Artist',cover:'https://example.com/cover.jpg',album:'Album'};
render({...base,vinyl:{...base.vinyl,automatic:true,state:'matched',track}});
assert.equal(elements['album-name'].textContent,track.title);
assert.equal(elements['cover'].hidden,false);
assert.equal(elements['vinyl-panel'].hidden,true);
render({...base,vinyl:{...base.vinyl,automatic:true,state:'matched',track,transition_pending:true}});
assert.equal(elements['album-name'].textContent,'Vinyl');
assert.equal(elements['cover'].hidden,true);
assert.equal(elements['metadata-status'].hidden,true);
render({...base,source:'spotify',spotify:{state:'ready',connected:true}});
assert.equal(elements['vinyl-panel'].hidden,true);
assert.equal(elements['playback-controls'].hidden,false);
assert.equal(elements['source-spotify'].attrs['aria-pressed'],'true');
render({...base,source:'plexamp',plexamp:{connected:true}});
assert.equal(elements['source-plexamp'].attrs['aria-pressed'],'true');
assert.equal(elements['source-spotify'].attrs['aria-pressed'],'false');
render({...base,source:'cd'});
assert.equal(elements['track-section'].hidden,false);
assert.equal(elements['queue-section'],undefined);
assert.equal(elements['vinyl-panel'].hidden,true);
render({...base,source:'cd',disc:{present:true,inserted:false,ejected:true,id:'TESTDISC1',tracks:[{number:1,title:'Song',seconds:100,ready:true}]},player:{state:'play',track:1},queue:{upcoming:[],previous:false}});
assert.equal(elements['eject'].disabled,true);
assert.equal(elements['play'].disabled,false);
assert.equal(elements['track-list'].children.length,1);
assert.equal(elements['disc-message'].hidden,false);
assert.equal(elements['track-title'].textContent,'Song');
console.log('Frontend: vinyl idle/listening/match/unplugged, streaming and CD transitions passed');
render({...base,source:'dvd',dvd:{state:'detected',title:'Test film',present:true,seconds:6650,dutch_subtitles:true,audio_languages:['Engels','Frans'],width:720,height:576,aspect:'16:9'}});
assert.equal(elements['dvd-duration'].textContent,'1 u 50 min');
assert.equal(elements['dvd-subtitles'].textContent,'Nederlands · automatisch');
assert.equal(elements['dvd-eject'].disabled,false);
assert.equal(elements['dvd-audio'].textContent,'Engels · Frans');
render({...base,source:'dvd',dvd:{state:'absent',present:false}});
assert.equal(elements['dvd-eject'].disabled,true);
assert.equal(elements['dvd-duration'].textContent,'—');
assert.equal(elements['dvd-stop'].hidden,true);
console.log('DVD VLC details and eject controls passed');
render({...base,source:'cd',disc:{...base.disc,present:true},archive:{blocked:2,drive_blocked:false,error:'Drive herstel'}});
assert.equal(elements['archive-retry'].hidden,false);
assert.equal(elements['archive-status'].textContent,'Drive herstel');
render({...base,source:'cd',archive:{blocked:2,drive_blocked:true,error:'USB-drive opnieuw aansluiten'}});
assert.equal(elements['archive-retry'].hidden,true);
assert.equal(elements['archive-status'].hidden,false);
render({...base,source:'cd',disc:{...base.disc,present:true},archive:{buffer_full:true,buffer_message:'Lokale buffer vol; wacht op de muziekserver.',error:'Server offline'}});
assert.equal(elements['archive-status'].textContent,'Server offline Lokale buffer vol; wacht op de muziekserver.');
console.log('Import recovery controls and blocked-drive notice passed');
(async()=>{
 render({...base,source:'plexamp',plexamp:{connected:true}});
 let finish;
 context.fetch=()=>new Promise(resolve=>finish=resolve);
 const reading=vm.runInContext('readStatus()',context);
 vm.runInContext("busy=true;setSource('vinyl')",context);
 assert.equal(elements['source-vinyl'].attrs['aria-pressed'],'true');
 finish({ok:true,json:async()=>({...base,source:'plexamp'})});
 await reading;
 assert.equal(elements['source-vinyl'].attrs['aria-pressed'],'true');
 assert.equal(vm.runInContext('state.source',context),'plexamp');
 context.fetch=async()=>({ok:true,json:async()=>base});
 await vm.runInContext('readStatus()',context);
 assert.equal(vm.runInContext('state.source',context),'vinyl');
 assert.equal(elements['source-vinyl'].attrs['aria-pressed'],'true');
 console.log('Stale Plexamp status cannot override a Vinyl click; confirmed Vinyl status accepted');
})().catch(e=>{console.error(e);process.exitCode=1});
