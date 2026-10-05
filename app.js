const $=s=>document.querySelector(s),NS='http://www.w3.org/2000/svg',G=300;
const COL={idle:'#8CA3B8',delivering:'#19C3AE',negotiating:'#F5A524',failed:'#F2555A'},PRI={high:'#8F7CFF',normal:'#4F9DFF',low:'#6B7C8C'};
const KIND={task:['#4F9DFF','Task'],auction:['#19C3AE','Auction'],yield:['#F5A524','Intersection'],fault:['#F2555A','Failure'],heal:['#8F7CFF','Self-healing'],done:['#7BD389','Delivery']};
const INTER=[{id:'I1',x:100,y:100,r:12},{id:'I2',x:200,y:200,r:12}];
let mode='live',S=null,running=false,timer=null,n=0,hist=[],replay=[],ri=0,sel=null,seen=0,pick=null,filt='all',busy=false;
const kind=m=>/reassigned|repaired|released/i.test(m)?'heal':/failed|stranded|blocked|critical/i.test(m)?'fault':/yield|cleared|negotiat/i.test(m)?'yield':/won|bid/i.test(m)?'auction':/completed|picked up/i.test(m)?'done':'task';
const el=(t,a={},p)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);p&&p.append(e);return e};
const api=async(p,b)=>{const r=await fetch('/api/'+p,{method:b===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:b===undefined?undefined:JSON.stringify(b)});if(!r.ok)throw new Error(p);return r.json()};
const banner=t=>{const b=$('#banner');b.hidden=!t;b.innerHTML=t||''};
const fy=y=>G-y;

/* ---------- map scaffold ---------- */
const map=$('#map'),L={};
function scaffold(){map.innerHTML='';const bg=el('g',{},map);
 [100,200].forEach(v=>{el('path',{d:`M${v} 0V300M0 ${fy(v)}H300`,class:'road'},bg);el('path',{d:`M${v} 0V300M0 ${fy(v)}H300`,class:'lane'},bg)});
 L.zones=INTER.map(i=>{const g=el('g',{},map);el('circle',{cx:i.x,cy:fy(i.y),r:i.r,class:'zone'},g);const t=el('text',{x:i.x,y:fy(i.y)+i.r+6,'text-anchor':'middle'},g);t.textContent=i.id;return g});
 L.tasks=el('g',{},map);L.veh=el('g',{},map);L.veh.m={};
 L.pick=el('g',{},map)}
map.addEventListener('click',e=>{if(!pick)return;const p=map.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const q=p.matrixTransform(map.getScreenCTM().inverse());
 const x=Math.round(Math.max(0,Math.min(G,q.x))),y=Math.round(Math.max(0,Math.min(G,G-q.y)));
 const f=$('#taskForm');if(pick==1){f.px.value=x;f.py.value=y;pick=2;toast('Now click the dropoff point','task')}else{f.dx.value=x;f.dy.value=y;pick=null;map.classList.remove('picking');$('#dlg').showModal()}});

function vehEl(v){let g=L.veh.m[v.id];if(g)return g;g=el('g',{class:'veh'},L.veh);
 el('circle',{r:7,class:'pulse'},g);el('circle',{r:9,fill:'none',stroke:'#2A3F54','stroke-width':1.6},g);
 el('circle',{r:9,class:'ring',pathLength:100,'stroke-dasharray':'100 100'},g);el('circle',{r:5.5,class:'body'},g);
 const t=el('text',{y:-12,'text-anchor':'middle'},g);t.textContent=v.id;L.veh.m[v.id]=g;return g}

/* ---------- render ---------- */
function render(){
 if(!S)return;const V=S.vehicles,T=S.tasks;
 $('#map').style.setProperty('--tick',($('#speed').value*.95/1000)+'s');
 V.forEach(v=>{const g=vehEl(v);g.style.transform=`translate(${v.x}px,${fy(v.y)}px)`;g.setAttribute('class','veh '+v.status);
  g.children[3].setAttribute('fill',COL[v.status]);const r=g.children[2];r.setAttribute('stroke',v.battery<25?COL.failed:COL[v.status]);r.setAttribute('stroke-dasharray',`${v.battery} 100`)});
 L.tasks.innerHTML='';const vm=Object.fromEntries(V.map(v=>[v.id,v]));
 V.forEach(v=>{if(v.destination&&v.status!=='failed')el('line',{x1:v.x,y1:fy(v.y),x2:v.destination[0],y2:fy(v.destination[1]),stroke:COL[v.status],'stroke-width':.7,'stroke-dasharray':'2 2',opacity:.7},L.tasks)});
 T.filter(t=>t.status!=='completed').forEach(t=>{const c=PRI[t.priority],car=t.assigned_to&&vm[t.assigned_to]&&vm[t.assigned_to].current_task===t.id&&vm[t.assigned_to].destination&&vm[t.assigned_to].destination.join()===t.dropoff.join();
  if(!car){el('rect',{x:t.pickup[0]-3.5,y:fy(t.pickup[1])-3.5,width:7,height:7,fill:t.status==='pending'?'none':c+'55',stroke:c,'stroke-width':1.2},L.tasks);const x=el('text',{x:t.pickup[0]+6,y:fy(t.pickup[1])+2},L.tasks);x.textContent=t.id}
  el('path',{d:`M${t.dropoff[0]} ${fy(t.dropoff[1])}m0-6l5 6l-5 6l-5-6z`,fill:c,opacity:.9},L.tasks);const y=el('text',{x:t.dropoff[0]+7,y:fy(t.dropoff[1])+2},L.tasks);y.textContent=t.id+' drop'});
 INTER.forEach((i,k)=>{const inn=V.filter(v=>v.status!=='failed'&&Math.hypot(v.x-i.x,v.y-i.y)<=i.r),w=V.filter(v=>v.status==='negotiating'&&Math.hypot(v.x-i.x,v.y-i.y)<i.r+45);
  L.zones[k].children[0].setAttribute('class','zone'+(inn.length||w.length?' busy':''));
  L.zones[k].children[1].textContent=i.id+(inn.length?` · ${inn.map(v=>v.id).join(',')} crossing`:'')+(w.length?` · ${w.map(v=>v.id).join(',')} yielding`:'')});
 $('#tickLbl').textContent=(mode==='live'?'live engine':'replay')+' · tick '+n;
 $('#fleet').innerHTML=V.map(v=>`<button class="vc ${sel===v.id?'sel':''}" data-id="${v.id}" style="--c:${COL[v.status]}"><div class="r"><b>${v.id}</b><span class="pill">${v.status}</span></div>
  <div class="bar" style="--c:${v.battery<25?COL.failed:COL.delivering}"><i style="width:${v.battery}%"></i></div>
  <div class="r"><small>${v.battery}% battery · cap ${v.capacity}</small><small>${v.current_task?v.current_task+' → ('+v.destination.map(Math.round)+')':'no task'}</small></div></button>`).join('');
 $('#selPanel').innerHTML=sel?`<div class="act"><b style="font-size:12px;align-self:center">${sel}</b>${['breakdown','battery_critical','blocked'].map(m=>`<button data-fail="${m}" ${mode!=='live'?'disabled':''}>${m.replace('_',' ')}</button>`).join('')}<button data-repair ${mode!=='live'?'disabled':''}>repair</button></div>`:`<p class="hint" style="color:var(--mute);margin:8px 0 0;font-size:12px">Select a vehicle to fail or repair it.</p>`;
 $('#tasks').innerHTML=T.length?T.slice().reverse().map(t=>`<div class="tk ${t.status==='completed'?'done':''}" style="--c:${PRI[t.priority]}"><b>${t.id}</b><span class="chip">${t.priority}</span><span>${t.status==='pending'?'waiting for bids':t.status+(t.assigned_to?' · '+t.assigned_to:'')}</span><small>${t.pickup.map(Math.round)} → ${t.dropoff.map(Math.round)}</small></div>`).join(''):'<p style="color:var(--mute)">No tasks yet. Use Add task.</p>';
 const row=e=>{const k=kind(e.message);return `<li style="--c:${KIND[k][0]}" data-k="${k}"><time>t=${e.time}</time><span>${e.message}</span></li>`};
 $('#feed').innerHTML=S.log.slice(-40).reverse().map(row).join('');
 S.log.slice(seen).forEach(e=>{const k=kind(e.message);if(['fault','heal','yield'].includes(k)&&seen||k==='fault'||k==='heal')toast(e.message,k)});seen=S.log.length;
 analytics(row);bFailUpd()}
function toast(m,k){const d=document.createElement('div');d.className='toast';d.style.setProperty('--c',KIND[k][0]);d.textContent=m;const t=$('#toasts');t.append(d);while(t.children.length>3)t.firstChild.remove();setTimeout(()=>d.remove(),6500)}

function analytics(row){const L2=S.log,V=S.vehicles,T=S.tasks;
 const win=/^Vehicle (\w+) won Task (\w+) \(best of (\d+) bid\(s\): score ([\d.]+), ([\d.]+) units away, battery (\d+)%/,re=/^Task (\w+) reassigned from (\w+) to (\w+) \(best of (\d+) bid\(s\): score ([\d.]+), ([\d.]+) units away, battery (\d+)%/;
 const rows=[];L2.forEach(e=>{let m=e.message.match(win);if(m)rows.push([e.time,m[2],'Auction','—',m[1],m[3],m[4],m[5],m[6]]);else if(m=e.message.match(re))rows.push([e.time,m[1],'Re-auction',m[2],m[3],m[4],m[5],m[6],m[7]])});
 const c=r=>L2.filter(e=>r.test(e.message)).length,avg=Math.round(V.reduce((a,v)=>a+v.battery,0)/(V.length||1));
 $('#metrics').innerHTML=[[S.completed_count,'Deliveries completed'],[T.filter(t=>t.status==='assigned').length,'Tasks in progress'],[T.filter(t=>t.status==='pending').length,'Tasks waiting for bids'],[V.filter(v=>v.status==='failed').length,'Vehicles failed'],[c(/reassigned/),'Self-healing re-auctions'],[c(/yielded/),'Intersection yields'],[rows.length,'Auctions held'],[avg+'%','Average battery']].map(([a,b])=>`<div class="m"><b>${a}</b><span>${b}</span></div>`).join('');
 $('#auctions').innerHTML='<tr><th>Time</th><th>Task</th><th>Type</th><th>Released by</th><th>Winner</th><th>Bids</th><th>Score</th><th>Distance</th><th>Battery</th></tr>'+(rows.length?rows.slice().reverse().map(r=>`<tr><td>t=${r[0]}</td><td><b>${r[1]}</b></td><td>${r[2]}</td><td>${r[3]}</td><td><b>${r[4]}</b></td><td>${r[5]}</td><td>${r[6]}</td><td>${r[7]} u</td><td>${r[8]}%</td></tr>`).join(''):'<tr><td colspan="9">No auctions yet.</td></tr>');
 $('#chips').innerHTML=['all',...Object.keys(KIND)].map(k=>`<button data-chip="${k}" class="${filt===k?'on':''}">${k==='all'?'All':KIND[k][1]}</button>`).join('');
 $('#fullLog').innerHTML=L2.slice().reverse().map(row).filter(h=>filt==='all'||h.includes(`data-k="${filt}"`)).join('');
 chart('#ch1',hist.map(h=>h.done),null);chart('#ch2',hist.map(h=>h.bat),100)}
function chart(s,d,max){const svg=$(s);if(d.length<2){svg.innerHTML='';return}const mx=max||Math.max(1,...d),w=400,h=140;
 svg.innerHTML=`<path d="${d.map((v,i)=>(i?'L':'M')+(i/(d.length-1)*w).toFixed(1)+' '+(h-8-v/mx*(h-16)).toFixed(1)).join('')}"/>`}

/* ---------- engine control ---------- */
function ingest(s,adv=true){S=s;if(adv)n++;hist.push({done:s.completed_count,bat:s.vehicles.reduce((a,v)=>a+v.battery,0)/(s.vehicles.length||1)});render()}
async function step(){if(busy)return;busy=true;try{if(mode==='live')ingest(await api('tick',{}));else if(ri<replay.length)ingest(replay[ri++]);else pause()}catch(e){pause();banner('Lost connection to server.py. Restart it and press Reset.')}busy=false}
function run(){running=true;$('#bRun').textContent='Pause';clearInterval(timer);timer=setInterval(step,+$('#speed').value)}
function pause(){running=false;$('#bRun').textContent='Start';clearInterval(timer)}
async function reset(){pause();n=0;hist=[];seen=0;ri=0;sel=null;scaffold();$('#toasts').innerHTML='';
 if(mode==='live')S=await api('reset',{random:$('#scenario').value==='1'});else S=replay[0];ingest(S,false);if(mode!=='live')ri=1}
async function act(p,b){if(mode!=='live')return;try{S=await api(p,b);ingest(S,false)}catch(e){banner('Action failed.')}}
function bFailUpd(){const v=S&&S.vehicles.find(v=>v.id==='V3');const f=v&&v.status==='failed';$('#bFail').textContent=f?'Repair V3':'Fail V3';$('#bFail').disabled=mode!=='live'||!v;$('#bAdd').disabled=mode!=='live'}

/* ---------- wiring ---------- */
$('#bRun').onclick=()=>running?pause():run();$('#bStep').onclick=step;$('#bReset').onclick=reset;$('#scenario').onchange=()=>mode==='live'&&reset();
$('#speed').onchange=()=>{running&&run();render()};
$('#bFail').onclick=()=>{const f=S.vehicles.find(v=>v.id==='V3').status==='failed';act(f?'repair':'fail',{id:'V3',mode:'breakdown'})};
$('#fleet').onclick=e=>{const b=e.target.closest('.vc');if(b){sel=sel===b.dataset.id?null:b.dataset.id;render()}};
$('#selPanel').onclick=e=>{const b=e.target.closest('button');if(!b||!sel)return;b.dataset.repair!==undefined?act('repair',{id:sel}):act('fail',{id:sel,mode:b.dataset.fail})};
$('#chips').onclick=e=>{const b=e.target.closest('[data-chip]');if(b){filt=b.dataset.chip;render()}};
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));$('#live').hidden=t.dataset.view!=='live';$('#analytics').hidden=t.dataset.view!=='analytics'});
const rnd=()=>Math.round(10+Math.random()*280);
$('#bAdd').onclick=()=>{const f=$('#taskForm');[f.px,f.py,f.dx,f.dy].forEach(i=>i.value=i.value||rnd());$('#dlg').showModal()};
$('#tfRand').onclick=()=>{const f=$('#taskForm');[f.px,f.py,f.dx,f.dy].forEach(i=>i.value=rnd())};
$('#tfCancel').onclick=()=>$('#dlg').close();
$('#tfPick').onclick=()=>{$('#dlg').close();pick=1;map.classList.add('picking');document.querySelector('[data-view=live]').click();toast('Click the pickup point on the map','task')};
$('#taskForm').onsubmit=e=>{const f=e.target;if(e.submitter&&e.submitter.value==='ok')act('task',{pickup:[+f.px.value,+f.py.value],dropoff:[+f.dx.value,+f.dy.value],priority:f.pr.value})};
$('.legend').innerHTML=Object.entries(COL).map(([k,c])=>`<span><i style="--c:${c}"></i>${k}</span>`).join('')+'<span>▢ pickup</span><span>◆ dropoff</span>';

(async()=>{scaffold();
 try{S=await api('state');mode='live'}catch(e){
  try{const t=await(await fetch('sample_states.jsonl')).text();replay=t.trim().split('\n').map(JSON.parse);mode='replay';
   banner('<b>Replay mode.</b> The engine server is not running, so this plays the 60 recorded ticks. Run <code>python server.py</code> and open http://localhost:8000 for the live engine with working controls.')}
  catch(e2){banner('<b>Cannot load data.</b> Run <code>python server.py</code> in this folder, then open http://localhost:8000.');return}}
 if(mode==='replay')await reset();else ingest(S,false)})();
