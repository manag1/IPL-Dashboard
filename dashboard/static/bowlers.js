let playerId=null,careerChart=null,runsChart=null,srChart=null,phaseChart=null,dismissChart=null;const $=id=>document.getElementById(id);const esc=v=>String(v??'').replace(/[&<>'"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[m]));async function get(u){const r=await fetch(u);if(!r.ok)throw Error(await r.text());return r.json()}
let filterCatalog={years:[],teams:[],venues:[]},filterState={year:new Set(),opponent:new Set(),venue:new Set()};
function params(){const q=new URLSearchParams();Object.entries(filterState).forEach(([k,s])=>s.forEach(v=>q.append(k,v)));return q}
function vals(k){return k==='year'?filterCatalog.years:k==='opponent'?filterCatalog.teams:filterCatalog.venues}function label(k){return k==='year'?'Year':k==='opponent'?'Opposition':'Venue'}
function renderFilters(){const root=$('headerFilterValues'),field=$('headerFilterField').value,set=filterState[field];root.innerHTML=vals(field).map(v=>`<label class="filter-check"><input type="checkbox" value="${esc(v)}" ${set.has(String(v))?'checked':''}><span>${esc(v)}</span></label>`).join('')||'<span class="muted">Select a bowler first</span>';root.querySelectorAll('input').forEach(x=>x.onchange=()=>{x.checked?set.add(x.value):set.delete(x.value);renderSummary()});renderSummary()}
function renderSummary(){const a=[];Object.entries(filterState).forEach(([k,s])=>s.forEach(v=>a.push(`<span class="selected-filter-chip"><b>${label(k)}:</b> ${esc(v)}</span>`)));$('selectedFilterSummary').innerHTML=a.length?a.join(''):'<span class="selected-filter-empty">No filters selected</span>'}
async function loadFilters(id){const x=await get(`/api/bowler/${id}/filters`);filterCatalog={years:(x.years||[]).map(String),teams:x.teams||[],venues:x.venues||[]};filterState={year:new Set(),opponent:new Set(),venue:new Set()};renderFilters()}
function destroy(c){if(c)c.destroy()}const colors=['#2f6de6','#2c8e9a','#f0a62b','#7651d8','#f58a98','#7390b8'];

function chartFixedTooltip(context){
  const {chart,tooltip}=context;
  let el=document.getElementById('chart-fixed-tooltip');
  if(!el){el=document.createElement('div');el.id='chart-fixed-tooltip';document.body.appendChild(el);}
  if(tooltip.opacity===0){el.style.opacity='0';return;}
  const title=(tooltip.title||[])[0]||'';
  const lines=[];
  (tooltip.body||[]).forEach(item=>(item.lines||[]).forEach(v=>{if(v)lines.push(String(v));}));
  el.innerHTML=`<div class="ct-title">${esc(title)}</div>${lines.map(v=>{const m=v.match(/^([^:]+):\s*(.*)$/);return m?`<div class="ct-row"><span>${esc(m[1])}</span><b>${esc(m[2])}</b></div>`:`<div class="ct-row"><span>${esc(v)}</span></div>`;}).join('')}`;
  el.style.opacity='1';el.style.left='0px';el.style.top='0px';
  const rect=chart.canvas.getBoundingClientRect();let left=rect.left+(tooltip.caretX||0),top=rect.top+(tooltip.caretY||0)-el.offsetHeight-9;const w=el.offsetWidth,h=el.offsetHeight,pad=8;
  left=Math.max(w/2+pad,Math.min(window.innerWidth-w/2-pad,left));if(top<pad)top=Math.min(window.innerHeight-h-pad,rect.top+(tooltip.caretY||0)+18);top=Math.max(pad,top);
  el.style.left=`${left}px`;el.style.top=`${top}px`;
}
function hideChartFixedTooltip(){const el=document.getElementById('chart-fixed-tooltip');if(el)el.style.opacity='0';}
window.addEventListener('scroll',hideChartFixedTooltip,true);

function chartOpts(yTitle=''){return{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{displayColors:false,backgroundColor:'#10234b',titleColor:'#fff',bodyColor:'#eef4ff'}},scales:{x:{grid:{display:false},ticks:{color:'#667085',font:{size:9}}},y:{beginAtZero:true,grid:{color:'rgba(148,163,184,.18)'},ticks:{color:'#667085',font:{size:9}},title:{display:!!yTitle,text:yTitle}}}}}
function kpis(s){
  const data=[
    ['MATCHES',s.matches??'—'],
    ['INNINGS',s.innings??'—'],
    ['BEST BOWLING',s.best??'—'],
    ['WICKETS',s.wickets??'—'],
    ['AVERAGE',s.average??'—'],
    ['ECONOMY',s.economy??'—'],
    ['STRIKE RATE',s.strike_rate??'—'],
    ['3W / 4W / 5W HAULS',`${s.three_w??0} / ${s.four_w??0} / ${s.five_w??0}`],
    ['DOT %',(s.dot_percentage??'—')+(s.dot_percentage!=null?'%':'')]
  ];
  $('kpis').innerHTML=data.map(([l,v])=>`<div class="kpi"><div class="lab">${esc(l)}</div><div class="val">${esc(v)}</div></div>`).join('');
}
function renderHistory(a){
  // Shared visual contract with Batter Stats: same DOM hierarchy, font weights, logo fallback and period placement.
  const slug=t=>String(t||'').trim().toLowerCase().replace(/&/g,'and').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'');
  const initials=t=>String(t||'').split(/\s+/).filter(Boolean).map(v=>v[0]).join('').slice(0,3).toUpperCase();
  $('history').innerHTML=a.length?a.map(r=>{
    const team=String(r.team||r.team_name||''); const logo=slug(team);
    return `<div class="team-history-row"><span class="team-history-name"><span class="team-logo-fallback">${esc(initials(team))}</span><img class="team-logo" src="/static/team_logos/${esc(logo)}.png" alt="" aria-hidden="true" onerror="this.style.display='none';this.previousElementSibling.style.display='inline-flex'"><b class="team-history-label">${esc(team)}</b></span><b class="team-history-period">(${esc(r.period)})</b></div>`;
  }).join(''):'<div class="muted">No history</div>';
}
function renderLegends(a,id,totalId){$(id).innerHTML=a.map((r,i)=>`<div><i style="background:${colors[i%colors.length]}"></i><span>${esc(r.phase||r.kind||'Other')}</span><b>${r.wickets??r.count}</b></div>`).join('');$(totalId).textContent=a.reduce((s,r)=>s+Number(r.wickets??r.count??0),0)}
function renderPhase(a){destroy(phaseChart);renderLegends(a,'phaseLegend','phaseTotal');phaseChart=new Chart($('phaseChart'),{type:'doughnut',data:{labels:a.map(r=>r.phase),datasets:[{data:a.map(r=>r.wickets),backgroundColor:colors,borderWidth:1,borderColor:'#fff'}]},options:{responsive:true,maintainAspectRatio:false,cutout:'62%',plugins:{legend:{display:false}}}})}
function renderDismiss(a){destroy(dismissChart);renderLegends(a,'dismissLegend','dismissTotal');dismissChart=new Chart($('dismissChart'),{type:'doughnut',data:{labels:a.map(r=>r.kind),datasets:[{data:a.map(r=>r.count),backgroundColor:colors,borderWidth:1,borderColor:'#fff'}]},options:{responsive:true,maintainAspectRatio:false,cutout:'62%',plugins:{legend:{display:false}}}})}
function careerBarColor(r){const w=Number(r.wickets||0);if(w>=5)return '#2f8f63';if(w===4)return '#d85f2f';if(w===3)return '#c28b1c';return '#2f6de6'}
const momStarPlugin={id:'momStars',afterDatasetsDraw(chart){const data=chart.options?.plugins?.momStars?.data||[];const meta=chart.getDatasetMeta(0);const ctx=chart.ctx;ctx.save();ctx.fillStyle='#c58b16';ctx.font='bold 16px Arial';ctx.textAlign='center';ctx.textBaseline='bottom';data.forEach((r,i)=>{if(r&&Number(r.is_mom)===1){const el=meta.data[i];if(el)ctx.fillText('★',el.x,Math.max(chart.chartArea.top+16,el.y-7))}});ctx.restore()}};
function careerTooltipOptions(){return{enabled:false,external:chartFixedTooltip,callbacks:{title(items){const r=items[0]?.raw?.meta;return r?`${r.sequence}. ${r.match_date||'—'} vs ${r.opposition||'—'}`:'Spell'},label(item){const r=item.raw?.meta;if(!r)return '';return [`Overs: ${r.overs??'—'}`,`Maidens: ${r.maidens??0}`,`Runs: ${r.runs_conceded??0}`,`Wickets: ${r.wickets??0}`,`Economy: ${r.economy??'—'}`,`Average: ${r.average??'—'}`,`SR: ${r.strike_rate??'—'}`,...(Number(r.is_mom||0)===1?['★ Player of the Match']:[])]}}}}
function charts(x){
  destroy(careerChart);destroy(runsChart);destroy(srChart);
  const career=x.career||[];
  careerChart=new Chart($('careerChart'),{type:'bar',data:{labels:career.map(r=>r.sequence),datasets:[{label:'Wickets',data:career.map(r=>({x:r.sequence,y:r.wickets,meta:r})),backgroundColor:career.map(careerBarColor),borderRadius:3}]},options:{...chartOpts('Wickets'),plugins:{...chartOpts('').plugins,tooltip:careerTooltipOptions(),momStars:{data:career}},scales:{x:{grid:{display:false},ticks:{color:'#667085',font:{size:9}},title:{display:true,text:'Spells'}},y:{beginAtZero:true,grid:{color:'rgba(148,163,184,.18)'},ticks:{color:'#667085',font:{size:9}},title:{display:true,text:'Wickets'}}}},plugins:[momStarPlugin]});
  const s=x.season||[];
  runsChart=new Chart($('runsChart'),{type:'bar',data:{labels:s.map(r=>r.year),datasets:[{label:'Wickets',data:s.map(r=>r.wickets),backgroundColor:'#2f6de6',borderRadius:3}]},options:chartOpts('Wickets')});
  srChart=new Chart($('srChart'),{type:'line',data:{labels:s.map(r=>r.year),datasets:[{label:'Economy',data:s.map(r=>r.economy),borderColor:'#2c8e9a',backgroundColor:'rgba(44,142,154,.12)',tension:.35,fill:false,pointRadius:3}]},options:chartOpts('Economy')})
}
function renderMatches(a){$('matches').innerHTML=a.slice(0,20).map(r=>{const result=String(r.result||'—');const resultClass=result.toLowerCase().replace(/[^a-z]+/g,'-');return `<tr><td>${esc(r.match_date)}</td><td>${esc(r.opposition)}</td><td>${r.overs}</td><td>${r.runs_conceded}</td><td>${r.wickets}</td><td>${r.economy??'—'}</td><td>${r.dot_balls}</td><td class="match-result ${resultClass}">${esc(result)}</td><td>${esc(r.venue)}</td></tr>`}).join('')||'<tr><td colspan="9" class="muted">No bowling spells</td></tr>'}
const TEAM_COLORS={'Chennai Super Kings':'#f7c600','Mumbai Indians':'#004ba0','Kolkata Knight Riders':'#3a225d','Royal Challengers Bengaluru':'#d71920','Sunrisers Hyderabad':'#f26522','Punjab Kings':'#ed1b24','Delhi Capitals':'#17479e','Deccan Chargers':'#1c2b5a','Gujarat Titans':'#1c1c1c','Lucknow Super Giants':'#00a6a6','Rajasthan Royals':'#254aa5','Gujarat Lions':'#f15b2a','Kochi Tuskers Kerala':'#e65c3c'};
function teamColor(team){return TEAM_COLORS[team]||'#2f67c7'}
function renderOpps(a){
  const max=Math.max(...a.map(r=>Number(r.wickets)||0),1);
  $('opps').innerHTML=a.map(r=>{
    const width=Math.max(8,100*Number(r.wickets||0)/max), color=teamColor(r.opponent);
    return `<div class="opp"><div class="opp-name" title="${esc(r.opponent)}">${esc(r.opponent)}</div><div class="opp-bar-wrap"><div class="bar" style="width:${width}%;background:${color}"></div><div class="opp-tooltip"><strong>${esc(r.opponent)}</strong><span>Wickets <b>${r.wickets??0}</b></span><span>Average <b>${r.average??'—'}</b></span><span>Economy <b>${r.economy??'—'}</b></span></div></div><span class="opp-run">${r.wickets??0}</span></div>`;
  }).join('')||'<div class="muted">No opposition data</div>';
}
function renderMatchups(a){const draw=q=>{$('matchups').innerHTML=a.filter(r=>r.batter.toLowerCase().includes(q.toLowerCase())).map(r=>`<tr><td>${esc(r.batter)}</td><td>${r.balls}</td><td>${r.runs}</td><td>${r.fours}</td><td>${r.sixes}</td><td>${r.wickets}</td><td>${r.average??'—'}</td><td>${r.strike_rate??'—'}</td><td>${r.dot_percentage??'—'}%</td></tr>`).join('')||'<tr><td colspan="9" class="muted">No matching batter</td></tr>'};draw('');$('matchupSearch').oninput=e=>draw(e.target.value)}
async function ai(){if(!playerId)return;$('aiStatus').textContent='Generating bowling analysis…';try{const x=await get(`/api/bowler/${playerId}/ai-analysis?${params()}`),a=x.analysis||{};$('aiStatus').textContent=x.model||'Analysis';$('insights').innerHTML=(a.insights||[]).map(v=>`<div class="finding">${esc(v)}</div>`).join('');$('aiStrengths').innerHTML=(a.strengths||[]).map(v=>`<div class="finding"><strong>Strength:</strong> ${esc(v)}</div>`).join('');$('aiWatchouts').innerHTML=(a.watchouts||[]).map(v=>`<div class="finding"><strong>Watchout:</strong> ${esc(v)}</div>`).join('')}catch(e){$('aiStatus').textContent='AI analysis unavailable';$('insights').textContent=e.message}}
function portrait(n){$('portrait').textContent=n.split(/\s+/).map(x=>x[0]).slice(0,2).join('').toUpperCase()}
async function loadPlayer(id,reset=false){playerId=id;if(reset)await loadFilters(id);$('loadingOverlay').classList.add('show');try{const x=await get(`/api/bowler/${id}/overview?${params()}`);$('pname').textContent=x.player.player_name;$('pteam').textContent='IPL Bowling Profile';$('pmeta').textContent='Role: Bowler · Detailed ball-by-ball IPL analysis';portrait(x.player.player_name);const s=x.summary;$('smMatches').textContent=s.matches;$('smWickets').textContent=s.wickets;$('smBest').textContent=s.best;kpis(s);renderHistory(x.history||[]);renderPhase(x.phases||[]);renderDismiss(x.dismissals||[]);charts(x);renderMatches(x.matches||[]);renderOpps(x.oppositions||[]);renderMatchups(x.matchups||[]);ai()}catch(e){alert('Unable to load bowler: '+e.message)}finally{$('loadingOverlay').classList.remove('show')}}
let timer;function hideSuggestions(){const box=$('suggestions');box.innerHTML='';box.classList.remove('show')}function initSearch(){const input=$('search'),box=$('suggestions');input.oninput=e=>{clearTimeout(timer);const q=e.target.value.trim();if(!q){hideSuggestions();return}timer=setTimeout(async()=>{try{const a=await get('/api/bowlers/search?q='+encodeURIComponent(q));box.innerHTML=a.map(r=>`<div class="suggestion" data-id="${r.player_id}" data-name="${esc(r.player_name)}"><b>${esc(r.player_name)}</b></div>`).join('')||'<div class="suggestion"><span>No players found</span></div>';box.classList.add('show');box.querySelectorAll('.suggestion[data-id]').forEach(el=>el.onclick=()=>{const id=el.dataset.id,name=el.dataset.name;input.value=name;hideSuggestions();loadPlayer(Number(id),true)})}catch(err){console.error(err)}},180)};document.addEventListener('click',e=>{if(!e.target.closest('.searchbox'))hideSuggestions()});input.addEventListener('keydown',e=>{if(e.key==='Escape')hideSuggestions()})}
let modalChart=null;
const CHART_TITLES={careerChart:'Career Graph',runsChart:'Wickets Over the Years',srChart:'Economy Over the Years'};
function chartInstanceFor(id){return id==='careerChart'?careerChart:id==='runsChart'?runsChart:id==='srChart'?srChart:null}
function openChartMaximize(id){const source=chartInstanceFor(id),modal=$('chartModal'),canvas=$('chartModalCanvas');if(!source||!modal||!canvas)return;if(modalChart)modalChart.destroy();$('chartModalTitle').textContent=CHART_TITLES[id]||'Chart';modalChart=new Chart(canvas,{type:source.config.type,data:source.config.data,options:source.config.options,plugins:source.config.plugins||[]});modal.classList.add('show');requestAnimationFrame(()=>modalChart?.resize())}
function closeChartMaximize(){if(modalChart){modalChart.destroy();modalChart=null}$('chartModal')?.classList.remove('show')}
function setupChartMaximize(){document.querySelectorAll('.chart-maximize').forEach(btn=>btn.onclick=()=>openChartMaximize(btn.dataset.chart));$('closeChartModal')?.addEventListener('click',closeChartMaximize);$('chartModal')?.addEventListener('click',e=>{if(e.target===$('chartModal'))closeChartMaximize()})}
function openTableMaximize(kind){const modal=$('tableModal'),body=$('tableModalBody');if(!modal||!body)return;body.innerHTML='';const titles={matches:['Match by Match','Expanded match-by-match bowling details.'],matchups:['Batter Matchups','Expanded batter-vs-bowler matchup details.'],teamhistory:['Team History','Expanded franchise history for the selected bowler.'],opps:['Player vs Oppositions','Expanded opposition bowling breakdown.']};const meta=titles[kind]||['Expanded View',''];$('tableModalTitle').textContent=meta[0];$('tableModalSubtitle').textContent=meta[1];if(kind==='teamhistory'||kind==='opps'){const src=kind==='teamhistory'?$('history'):$('opps');if(src){const box=src.cloneNode(true);box.classList.add(kind==='opps'?'expanded-opps':'expanded-team-history');body.appendChild(box)}}else{const src=kind==='matches'?document.querySelector('.midgrid .tablewrap.tall'):document.querySelector('.bowler-matchups-card .tablewrap');if(src){const wrap=document.createElement('div');wrap.className='tablewrap expanded-table';wrap.appendChild(src.querySelector('table').cloneNode(true));body.appendChild(wrap)}}modal.classList.add('show')}
function setupTableMaximize(){document.querySelectorAll('.table-maximize').forEach(btn=>btn.onclick=()=>openTableMaximize(btn.dataset.table));$('closeTableModal')?.addEventListener('click',()=>$('tableModal')?.classList.remove('show'));$('tableModal')?.addEventListener('click',e=>{if(e.target===$('tableModal'))$('tableModal').classList.remove('show')})}
function syncAIModal(){const body=$('aiModalBody');if(!body)return;body.innerHTML=`${$('insights').innerHTML}${$('aiStrengths').innerHTML}${$('aiWatchouts').innerHTML}`;$('aiModalStatus').textContent=$('aiStatus').textContent}
function init(){initSearch();$('headerFilterField').onchange=renderFilters;$('applyFilters').onclick=()=>playerId&&loadPlayer(playerId,false);$('clearFilters').onclick=()=>{filterState={year:new Set(),opponent:new Set(),venue:new Set()};renderFilters();if(playerId)loadPlayer(playerId,false)};$('refreshAI').onclick=ai;$('aiInsightsTab').onclick=()=>document.getElementById('aiInsightsSection').scrollIntoView({behavior:'smooth'});$('downloadBtn').onclick=()=>window.print();$('maximizeAI')?.addEventListener('click',()=>{syncAIModal();$('aiModal').classList.add('show')});$('closeAIModal')?.addEventListener('click',()=>$('aiModal').classList.remove('show'));$('aiModal')?.addEventListener('click',e=>{if(e.target===$('aiModal'))$('aiModal').classList.remove('show')});setupChartMaximize();setupTableMaximize();renderFilters();}
document.addEventListener('DOMContentLoaded',init);
