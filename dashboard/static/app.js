let playerId=null,careerChart=null,runsChart=null,srChart=null,distChart=null,dismissChart=null;
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>'"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[m]));
async function get(u){const r=await fetch(u);if(!r.ok)throw Error(await r.text());return r.json()}

let filterCatalog={years:[],teams:[],venues:[]};
let filterState={year:new Set(),opponent:new Set(),venue:new Set()};

function params(){
  const q=new URLSearchParams();
  Object.entries(filterState).forEach(([field,values])=>values.forEach(v=>q.append(field,v)));
  return q;
}
function optionValues(field){return field==='year'?filterCatalog.years:field==='opponent'?filterCatalog.teams:filterCatalog.venues;}
function filterLabel(field){return field==='year'?'Year':field==='opponent'?'Opposition':'Venue';}
function renderSelectedFilters(){
  const root=$('selectedFilterSummary'); if(!root)return;
  const items=[];
  for(const [field,values] of Object.entries(filterState)){
    for(const value of values){
      items.push(`<span class=\"selected-filter-chip\"><b>${esc(filterLabel(field))}:</b> ${esc(value)}</span>`);
    }
  }
  root.innerHTML=items.length?items.join(''):'<span class=\"selected-filter-empty\">No filters selected</span>';
}
function renderHeaderFilters(){
  const root=$('headerFilterValues'); if(!root)return;
  const field=$('headerFilterField').value;
  const selected=filterState[field]||new Set();
  root.innerHTML=optionValues(field).map(v=>`<label class="filter-check"><input type="checkbox" value="${esc(v)}" ${selected.has(String(v))?'checked':''}><span>${esc(v)}</span></label>`).join('')||'<span class="muted">Select a player first</span>';
  root.querySelectorAll('input').forEach(cb=>cb.onchange=()=>{
    if(cb.checked) selected.add(cb.value); else selected.delete(cb.value);
    renderSelectedFilters();
  });
  renderSelectedFilters();
}
async function loadPlayerFilters(id){
  const x=await get(`/api/player/${id}/filters`);
  filterCatalog={years:(x.years||[]).map(String),teams:x.teams||[],venues:x.venues||[]};
  for(const field of ['year','opponent','venue']) filterState[field]=new Set([...filterState[field]].filter(v=>optionValues(field).map(String).includes(String(v))));
  renderHeaderFilters();
}
function initHeaderFilters(){
  $('headerFilterField').onchange=renderHeaderFilters;
  renderSelectedFilters();
  $('applyFilters').onclick=()=>playerId&&loadPlayer(playerId,false);
  $('clearFilters').onclick=()=>{filterState={year:new Set(),opponent:new Set(),venue:new Set()};renderHeaderFilters();renderSelectedFilters();if(playerId)loadPlayer(playerId,false);};
}
function chartDestroy(c){if(c)c.destroy()}
function chartDestroy(c){if(c)c.destroy()}

const DISMISSAL_COLORS=['#2f6de6','#2c8e9a','#f0a62b','#7651d8','#f58a98','#7390b8'];
const TEAM_COLORS={
  'Chennai Super Kings':'#f7c600',
  'Mumbai Indians':'#004ba0',
  'Kolkata Knight Riders':'#3a225d',
  'Royal Challengers Bengaluru':'#d71920',
  'Sunrisers Hyderabad':'#f26522',
  'Punjab Kings':'#ed1b24',
  'Delhi Capitals':'#17479e',
  'Deccan Chargers':'#1c2b5a',
  'Gujarat Titans':'#1c1c1c',
  'Lucknow Super Giants':'#00a6a6',
  'Rajasthan Royals':'#254aa5',
  'Gujarat Lions':'#f15b2a',
  'Rising Pune Supergiant':'#7b1e3a',
  'Kochi Tuskers Kerala':'#e65c3c',
  'Pune Warriors India':'#2855a3'
};
const teamColor=team=>TEAM_COLORS[team]||'#2f67c7';

function commonTooltip(){
  return {
    displayColors:false,
    padding:8,
    titleFont:{size:10,weight:'700'},
    bodyFont:{size:10},
    backgroundColor:'#10234b',
    titleColor:'#fff',
    bodyColor:'#eef4ff',
    callbacks:{label:ctx=>`${ctx.dataset.label||'Runs'}: ${Number(ctx.parsed.y??ctx.raw??0).toLocaleString()}`}
  };
}


function chartFixedTooltip(context){
  const {chart, tooltip}=context;
  let el=document.getElementById('chart-fixed-tooltip');
  if(!el){
    el=document.createElement('div');
    el.id='chart-fixed-tooltip';
    document.body.appendChild(el);
  }
  if(tooltip.opacity===0){el.style.opacity='0';return;}

  const title=(tooltip.title||[])[0]||'';
  const lines=[];
  (tooltip.body||[]).forEach(item=>{
    (item.lines||[]).forEach(v=>{
      if(v) lines.push(String(v));
    });
  });

  el.innerHTML=`<div class="ct-title">${esc(title)}</div>${lines.map(v=>{
    const m=v.match(/^([^:]+):\\s*(.*)$/);
    if(m) return `<div class="ct-row"><span>${esc(m[1])}</span><b>${esc(m[2])}</b></div>`;
    return `<div class="ct-row"><span>${esc(v)}</span></div>`;
  }).join('')}`;
  el.style.opacity='1';
  el.style.left='0px'; el.style.top='0px';

  const rect=chart.canvas.getBoundingClientRect();
  let left=rect.left+(tooltip.caretX||0);
  const anchorTop=rect.top+(tooltip.caretY||0);
  const w=el.offsetWidth, h=el.offsetHeight, pad=8;
  left=Math.max(w/2+pad,Math.min(window.innerWidth-w/2-pad,left));
  let top=anchorTop-h-9;
  if(top<pad) top=Math.min(window.innerHeight-h-pad,anchorTop+18);
  top=Math.max(pad,top);
  el.style.left=`${left}px`;
  el.style.top=`${top}px`;
}
function hideChartFixedTooltip(){
  const el=document.getElementById('chart-fixed-tooltip');
  if(el) el.style.opacity='0';
}
window.addEventListener('scroll',hideChartFixedTooltip,true);

function makeCharts(x){
  chartDestroy(careerChart);chartDestroy(runsChart);chartDestroy(srChart);chartDestroy(distChart);chartDestroy(dismissChart);
  const yearly=x.year||[],labels=yearly.map(r=>r.year);

  // Career graph: one bar per innings, showing that innings' runs.
  // A * above a bar marks a not-out innings; a golden star marks MoM.
  const careerRows=[...(x.matches||[])].reverse();
  const careerPoints=careerRows.map((row,i)=>{
    const runs=Number(row.runs||0), balls=Number(row.balls_faced||0);
    return {...row,innings_no:i+1};
  });
  const careerLabels=careerPoints.map(r=>String(r.innings_no));
  const careerBarColors=careerPoints.map(r=>Number(r.runs||0)>=100?'#1f9d55':(Number(r.runs||0)>=50?'#ef6c35':'#2f67c7'));
  const careerStarsPlugin={
    id:'careerStars',
    afterDatasetsDraw(chart){
      if(chart.canvas.id!=='careerChart')return;
      const meta=chart.getDatasetMeta(0),ctx=chart.ctx;
      meta.data.forEach((bar,i)=>{
        const row=careerPoints[i]; if(!row)return;
        const x=bar.x, top=bar.y-5;
        ctx.save(); ctx.textAlign='center'; ctx.textBaseline='bottom';
        if(Number(row.is_mom||0)===1){
          ctx.font='bold 14px Segoe UI, Arial'; ctx.fillStyle='#d4a017';
          ctx.fillText('★',x,top);
        }
        ctx.restore();
      });
    }
  };
  careerChart=new Chart($('careerChart'),{
    type:'bar',
    plugins:[careerStarsPlugin],
    data:{labels:careerLabels,datasets:[{
      label:'Runs',data:careerPoints.map(r=>r.runs),
      backgroundColor:careerBarColors,borderRadius:3,barPercentage:.78,categoryPercentage:.9
    }]},
    options:{
      responsive:true,maintainAspectRatio:false,
      interaction:{mode:'index',intersect:false},
      hover:{mode:'index',intersect:false},
      layout:{padding:{top:20}},
      plugins:{legend:{display:false},tooltip:{
        enabled:false,external:chartFixedTooltip,
        callbacks:{
          title:ctx=>{const r=careerPoints[ctx[0]?.dataIndex];return r?`${r.innings_no}. ${r.match_date||'—'} vs ${r.opposition||'—'}`:'Innings';},
          label:ctx=>{const r=careerPoints[ctx.dataIndex];return r?[
            `Score: ${Number(r.runs||0).toLocaleString()}${Number(r.is_out||0)===0?'*':''}`,
            `Balls: ${r.balls_faced??0}`,
            `SR: ${r.strike_rate??'—'}`,
            `4s / 6s: ${r.fours??0} / ${r.sixes??0}`,
            ...(Number(r.is_mom||0)===1?['★ Player of the Match']:[])
          ]:'Runs: —';}
        }
      }},
      scales:{x:{grid:{display:false},ticks:{font:{size:8},maxTicksLimit:18},title:{display:true,text:'Innings',font:{size:9,weight:'600'}}},
        y:{beginAtZero:true,grid:{color:'#e8edf5'},ticks:{font:{size:8}},title:{display:true,text:'Runs',font:{size:9,weight:'600'}}}}
    }
  });
  runsChart=new Chart($('runsChart'),{
    type:'bar',
    data:{labels,datasets:[{
      label:'Runs',
      data:yearly.map(r=>r.runs),
      backgroundColor:'#2f67c7',
      borderRadius:3,
      barPercentage:.78,
      categoryPercentage:.9
    }]},
    options:{
      responsive:true,maintainAspectRatio:false,
      interaction:{mode:'nearest',intersect:false},
      hover:{mode:'nearest',intersect:false},
      plugins:{
        legend:{display:false},
        tooltip:{
          ...commonTooltip(),
          enabled:false,
          external:chartFixedTooltip,
          boxWidth:10,
          boxHeight:10,
          callbacks:{
            title:ctx=>`${ctx[0]?.label??'—'}`,
            label:ctx=>{
              const row=yearly[ctx.dataIndex];
              return row?[
                `Innings: ${row.innings??'—'}`,
                `Runs: ${Number(row.runs??0).toLocaleString()}`,
                `Average: ${row.average??'—'}`,
                `SR: ${row.strike_rate??'—'}`,
                `50s / 100s: ${row['50s']??0} / ${row['100s']??0}`,
                `4s / 6s: ${row.fours??0} / ${row.sixes??0}`
              ]:'Runs: —';
            }
          }
        }
      },
      scales:{
        x:{grid:{display:false},ticks:{font:{size:8}}},
        y:{beginAtZero:true,grid:{color:'#e8edf5'},ticks:{font:{size:8}}}
      }
    }
  });

  srChart=new Chart($('srChart'),{
    type:'line',
    data:{labels,datasets:[{
      label:'Strike Rate',
      data:yearly.map(r=>r.strike_rate),
      borderColor:'#2563eb',
      backgroundColor:'#2563eb',
      borderWidth:2,
      pointRadius:2,
      pointHoverRadius:4,
      pointHitRadius:35,
      pointStyle:'circle',
      pointBorderWidth:2,
      pointBackgroundColor:'#fff',
      pointBorderColor:'#2563eb',
      tension:.35,
      spanGaps:true
    }]},
    options:{
      responsive:true,maintainAspectRatio:false,
      interaction:{mode:'nearest',intersect:false},
      hover:{mode:'nearest',intersect:false},
      plugins:{
        legend:{display:false},
        tooltip:{
          ...commonTooltip(),
          enabled:false,
          external:chartFixedTooltip,
          boxWidth:10,
          boxHeight:10,
          callbacks:{
            title:ctx=>`Year: ${ctx[0]?.label??'—'}`,
            label:ctx=>`SR: ${ctx.parsed.y??'—'}`,
            afterLabel:ctx=>{
              const row=yearly[ctx.dataIndex];
              return row?[
                `Innings: ${row.innings??'—'}`,
                `Balls: ${Number(row.balls||0).toLocaleString()}`
              ].join('\n'):'';
            }
          }
        }
      },
      scales:{
        x:{grid:{display:false},ticks:{font:{size:8}}},
        y:{grid:{color:'#e8edf5'},ticks:{font:{size:8}}}
      }
    }
  });

  const phases=x.phase_summary||[];
  const phaseLabels=phases.map(r=>r.phase.replace(/\s*\(.*?\)$/, ''));
  const phaseColors=['#2f6de6','#2c8e9a','#f0a62b'];
  distChart=new Chart($('distChart'),{
    type:'doughnut',
    data:{labels:phaseLabels,datasets:[{
      data:phases.map(r=>r.runs),
      backgroundColor:phases.map((_,i)=>phaseColors[i]),
      borderColor:'#fff',
      borderWidth:3,
      hoverOffset:5
    }]},
    options:{
      cutout:'66%',
      plugins:{
        legend:{display:false},
        tooltip:{
          enabled:false,
          external:chartFixedTooltip,
          titleColor:'#fff',
          bodyColor:'#eef4ff',
          padding:9,
          titleFont:{size:10,weight:'700'},
          bodyFont:{size:9},
          callbacks:{
            title:ctx=>ctx[0]?.label||'—',
            label:ctx=>{
              const row=phases[ctx.dataIndex];
              return row?[
                `Runs: ${Number(row.runs??0).toLocaleString()}`,
                `Average: ${row.average??'—'}`,
                `SR: ${row.strike_rate??'—'}`,
                `4s / 6s: ${row.fours??0} / ${row.sixes??0}`
              ]:'';
            }
          }
        }
      }
    }
  });
  const distColors=['#2f6de6','#2c8e9a','#f0a62b'];
  $('distLegend').innerHTML=phases.map((r,i)=>{
    const label=r.phase.replace(/\s*\(.*?\)$/, '');
    return `<div><span><i class="dot" style="background:${distColors[i]}"></i>${esc(label)}</span></div>`;
  }).join('')||'<div>No phase data</div>';

  const d=x.dismissals||[],total=d.reduce((a,b)=>a+(b.n||0),0);
  $('dismissTotal').textContent=total;
  dismissChart=new Chart($('dismissChart'),{
    type:'doughnut',
    data:{labels:d.map(r=>r.kind),datasets:[{
      data:d.map(r=>r.n),
      backgroundColor:d.map((_,i)=>DISMISSAL_COLORS[i%DISMISSAL_COLORS.length]),
      borderColor:'#fff',
      borderWidth:3,
      hoverOffset:4
    }]},
    options:{
      cutout:'66%',
      plugins:{
        legend:{display:false},
        tooltip:{
          enabled:false,
          external:chartFixedTooltip,
          padding:8,
          titleFont:{size:10,weight:'700'},
          bodyFont:{size:9},
          callbacks:{
            label:ctx=>{
              const value=Number(ctx.raw||0),pct=total?(100*value/total).toFixed(1):'0.0';
              return `${value} (${pct}%)`;
            }
          }
        }
      }
    }
  });
  $('dismissLegend').innerHTML=d.map((r,i)=>{
    const pct=total?(100*(r.n||0)/total).toFixed(1):'0.0';
    return `<div class="dismiss-legend-row"><span><i class="dot" style="background:${DISMISSAL_COLORS[i%DISMISSAL_COLORS.length]}"></i>${esc(r.kind)}</span></div>`;
  }).join('')||'<div>No dismissals</div>';
}


let modalChart=null, modalChartSource=null;
const CHART_TITLES={
  careerChart:'Career Graph',
  runsChart:'Season Stats',
  srChart:'Season Strike Rates',
  distChart:'Runs Distribution',
  dismissChart:'Dismissal Breakdown'
};
function chartInstanceFor(id){
  return id==='careerChart'?careerChart:id==='runsChart'?runsChart:id==='srChart'?srChart:id==='distChart'?distChart:id==='dismissChart'?dismissChart:null;
}
function openChartMaximize(id){
  const source=chartInstanceFor(id), modal=$('chartModal'), canvas=$('chartModalCanvas');
  if(!source||!modal||!canvas)return;
  if(modalChart){modalChart.destroy();modalChart=null;}
  modalChartSource=id;
  $('chartModalTitle').textContent=CHART_TITLES[id]||'Chart';
  const config={
    type:source.config.type,
    data:source.config.data,
    options:source.config.options,
    plugins:source.config.plugins||[]
  };
  modalChart=new Chart(canvas,config);
  modal.classList.add('show');
  requestAnimationFrame(()=>modalChart&&modalChart.resize());
}
function closeChartMaximize(){
  if(modalChart){modalChart.destroy();modalChart=null;}
  modalChartSource=null;
  $('chartModal')?.classList.remove('show');
  hideChartFixedTooltip();
}
function setupChartMaximize(){
  document.querySelectorAll('.chart-maximize').forEach(btn=>{
    btn.onclick=()=>openChartMaximize(btn.dataset.chart);
  });
  $('closeChartModal')?.addEventListener('click',closeChartMaximize);
  $('chartModal')?.addEventListener('click',e=>{if(e.target===$('chartModal'))closeChartMaximize()});
}


function wireOppositionTooltips(root){
  root.querySelectorAll('.opp').forEach(row=>{
    const tip=row.querySelector('.opp-tooltip');
    if(!tip) return;
    row.addEventListener('mouseenter',()=>{
      tip.style.display='block'; tip.style.opacity='0';
      const rr=row.querySelector('.opp-bar-wrap').getBoundingClientRect();
      const w=tip.offsetWidth,h=tip.offsetHeight,p=8;
      let left=rr.left+rr.width/2, top=rr.top-h-9;
      left=Math.max(w/2+p,Math.min(window.innerWidth-w/2-p,left));
      if(top<p) top=Math.min(window.innerHeight-h-p,rr.bottom+9);
      tip.style.left=`${left}px`; tip.style.top=`${Math.max(p,top)}px`;
      tip.style.transform='translateX(-50%)'; tip.style.position='fixed'; tip.style.zIndex='10001'; tip.style.opacity='1';
    });
    row.addEventListener('mouseleave',()=>{tip.style.opacity='0';tip.style.display='none'});
  });
}
function openTableMaximize(kind){
  const modal=$('tableModal'), body=$('tableModalBody');
  if(!modal||!body)return;
  body.innerHTML='';
  if(kind==='matches'){
    $('tableModalTitle').textContent='Match by Match';
    $('tableModalSubtitle').textContent='Expanded match-by-match batting details.';
    const wrap=document.createElement('div'); wrap.className='tablewrap expanded-table';
    const source=document.querySelector('.midgrid .tablewrap.tall');
    if(!source)return;
    const table=source.querySelector('table').cloneNode(true);
    wrap.appendChild(table); body.appendChild(wrap);
  }else if(kind==='matchups'){
    $('tableModalTitle').textContent='Bowler Matchups';
    $('tableModalSubtitle').textContent='Expanded bowler matchup batting details.';
    const source=document.querySelector('.bowler-matchups-card .tablewrap');
    if(!source)return;
    const wrap=document.createElement('div'); wrap.className='tablewrap expanded-table';
    wrap.appendChild(source.querySelector('table').cloneNode(true));
    body.appendChild(wrap);
  }else if(kind==='teamhistory'){
    $('tableModalTitle').textContent='Team History';
    $('tableModalSubtitle').textContent='Expanded franchise history for the selected player.';
    const source=$('history');
    if(!source)return;
    const box=source.cloneNode(true); box.classList.add('expanded-team-history');
    body.appendChild(box);
  }else if(kind==='opps'){
    $('tableModalTitle').textContent=$('oppTitle')?.textContent||'Player vs Oppositions';
    $('tableModalSubtitle').textContent='Expanded opposition breakdown. Hover a bar for details.';
    const source=$('opps');
    if(!source)return;
    const box=source.cloneNode(true); box.classList.remove('scrollbox'); box.classList.add('expanded-opps');
    body.appendChild(box); wireOppositionTooltips(body);
  }
  modal.classList.add('show');
}
function closeTableMaximize(){$('tableModal')?.classList.remove('show');}
function setupTableMaximize(){
  document.querySelectorAll('.table-maximize').forEach(btn=>btn.onclick=()=>openTableMaximize(btn.dataset.table));
  $('closeTableModal')?.addEventListener('click',closeTableMaximize);
  $('tableModal')?.addEventListener('click',e=>{if(e.target===$('tableModal'))closeTableMaximize()});
}

function setLoading(loading,text='Loading player analytics…'){document.body.classList.toggle('loading-player',loading);$('loadingOverlay').classList.toggle('show',loading);$('loadingText').textContent=text;}

function render(x){
  window.__CRICKET_CURRENT_DATA__=x;
  const s=x.stats;
  const playerName=x.player.player_name;
  $('pname').textContent=playerName;
  $('portrait').textContent=playerName.split(/\s+/).map(v=>v[0]).join('').slice(0,2).toUpperCase();
  $('oppTitle').textContent=`${playerName} vs OPPOSITIONS`;
  const last=x.teams.length?x.teams[0]:null;
  $('pteam').textContent=last?last.team_name:'—';
  $('pmeta').textContent='Generating player profile…';
  $('smMatches').textContent=(s.matches??0).toLocaleString();
  $('smRuns').textContent=(s.runs??0).toLocaleString();
  $('smHundreds').textContent=`${s['50s']??0} / ${s['100s']??0}`;

  const teamLogoSlug=team=>String(team||'').trim().toLowerCase().replace(/&/g,'and').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'');
  const teamInitials=team=>String(team||'').split(/\s+/).filter(Boolean).map(v=>v[0]).join('').slice(0,3).toUpperCase();
  $('history').innerHTML=x.teams.map(r=>{
    const team=String(r.team_name||'');
    const slug=teamLogoSlug(team);
    const initials=teamInitials(team);
    return `<div class="team-history-row"><span class="team-history-name"><span class="team-logo-fallback">${esc(initials)}</span><img class="team-logo" src="/static/team_logos/${slug}.png" alt="" aria-hidden="true" onerror="this.style.display='none';this.previousElementSibling.style.display='inline-flex'"><b class="team-history-label">${esc(team)}</b></span><b class="team-history-period">(${esc(r.period)})</b></div>`;
  }).join('')||'<div class="muted">No history</div>';
  $('kpis').innerHTML=[
    ['MATCHES',s.matches],
    ['INNINGS',s.innings],
    ['HIGHEST',s.highest],
    ['RUNS',(s.runs??0).toLocaleString()],
    ['AVERAGE',s.average??'—'],
    ['STRIKE RATE',s.strike_rate??'—'],
    ['50s / 100s',`${s['50s']??0} / ${s['100s']??0}`],
    ['4s / 6s',`${s.fours??0} / ${s.sixes??0}`],
    ['MoM',s.mom??0],
    ['CATCH / STUMP',`${s.catches??0} / ${s.stumpings??0}`]
  ].map(v=>`<div class="kpi"><div class="lab">${v[0]}</div><div class="val">${esc(v[1])}</div></div>`).join('');

  $('donutRuns').textContent=(s.runs??0).toLocaleString();
  $('matches').innerHTML=x.matches.map(r=>`<tr><td>${esc(r.match_date)}</td><td>${esc(r.opposition||'—')}</td><td><b>${esc(r.score)}</b></td><td>${r.balls_faced}</td><td>${r.fours}</td><td>${r.sixes}</td><td>${r.strike_rate??'—'}</td><td class="match-result ${String(r.result||'').toLowerCase().replace(/[^a-z]+/g,'-')}">${esc(r.result||'—')}</td><td>${esc(r.venue||'—')}</td></tr>`).join('')||'<tr><td colspan="9" class="muted">No batting innings under these filters.</td></tr>';

  const maxRuns=Math.max(1,...x.oppositions.map(r=>Number(r.runs||0)));
  $('opps').innerHTML=x.oppositions.map(r=>{
    const width=Math.max(8,100*Number(r.runs||0)/maxRuns);
    const color=teamColor(r.opposition);
    return `<div class="opp" style="--team:${color}">
      <div class="opp-name" title="${esc(r.opposition)}">${esc(r.opposition)}</div>
      <div class="opp-bar-wrap"><div class="bar" style="width:${width}%;background:${color}"></div>
        <div class="opp-tooltip">
          <strong>${esc(r.opposition)}</strong>
          <span>Runs <b>${Number(r.runs||0).toLocaleString()}</b></span>
          <span>Average <b>${r.average??'—'}</b></span>
          <span>SR <b>${r.strike_rate??'—'}</b></span>
          <span>50s / 100s <b>${r['50s']??0} / ${r['100s']??0}</b></span>
          <span>4s / 6s <b>${r.fours??0} / ${r.sixes??0}</b></span>
        </div>
      </div>
      <span class="opp-run">${Number(r.runs||0).toLocaleString()}</span>
    </div>`;
  }).join('')||'<div class="muted">No opposition data</div>';

  wireOppositionTooltips(document);

  const renderMatchups=(query='')=>{const q=query.trim().toLowerCase();const filtered=(x.matchups||[]).filter(r=>String(r.bowler||'').toLowerCase().includes(q));$('matchups').innerHTML=filtered.map(r=>`<tr><td>${esc(r.bowler)}</td><td>${r.balls}</td><td>${r.runs}</td><td>${r.fours??0}</td><td>${r.sixes??0}</td><td>${r.dismissals}</td><td>${r.average??'—'}</td><td>${r.strike_rate??'—'}</td><td>${r.dot_percentage??'—'}%</td></tr>`).join('')||'<tr><td colspan="9" class="muted">No matching bowler</td></tr>';}; renderMatchups($('bowlerMatchupSearch')?.value||''); if($('bowlerMatchupSearch')) $('bowlerMatchupSearch').oninput=e=>renderMatchups(e.target.value);

  $('insights').innerHTML='<div class="finding"><strong>Gemini analysis</strong><br>Generating a compact analysis from the statistics shown on this Overview page.</div>';
  $('aiStatus').textContent='AI analysis is being prepared…';
  makeCharts(x);
}

function clearAI(){
  $('insights').innerHTML='<div class="finding"><strong>Gemini analysis</strong><br>Select a player to generate evidence-based insights.</div>';
  $('aiStrengths').innerHTML='';$('aiWatchouts').innerHTML='';
  $('pmeta').textContent='Generating player profile…';
  if($('aiModalBody')) syncAIModal();
}

function renderAIList(target,title,items,kind){
  if(!items.length){$(target).innerHTML='';return}
  $(target).innerHTML=`<div class="ai-section ${kind}"><div class="ai-section-title">${title}</div><ul class="ai-list">${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`;
}

function syncAIModal(){
  $('aiModalStatus').textContent=$('aiStatus').textContent;
  $('aiModalBody').innerHTML=$('insights').innerHTML+$('aiStrengths').innerHTML+$('aiWatchouts').innerHTML;
}

async function loadAIAnalysis(id){
  $('aiStatus').textContent='Gemini is analysing the selected Overview statistics…';
  $('insights').innerHTML='<div class="ai-loading"><span class="spinner"></span><div><strong>Generating AI insights…</strong><small>Analysing yearly performance, phases, opposition, matchups and dismissals.</small></div></div>';
  $('aiStrengths').innerHTML='';$('aiWatchouts').innerHTML='';
  syncAIModal();
  try{
    const response=await get(`/api/player/${id}/ai-analysis?${params()}`);
    if(response.analysis?.status){
      $('aiStatus').textContent=response.analysis.message||'AI analysis unavailable.';
      $('pmeta').textContent='Player profile unavailable.';
      syncAIModal();
      return;
    }
    $('pmeta').innerHTML=esc(response.analysis?.profile||'Player profile unavailable.').replace(/\\n/g,'<br>');
    $('aiStatus').textContent=response.analysis?.headline||'AI analysis ready.';
    const insights=response.analysis?.insights||[];
    $('insights').innerHTML=insights.map(item=>`<div class="finding"><strong>${esc(item.title)}</strong><span>${esc(item.text)}</span></div>`).join('')||'<div class="finding">No additional insights were returned.</div>';
    renderAIList('aiStrengths','STRENGTHS',response.analysis?.strengths||[],'strengths');
    renderAIList('aiWatchouts','WEAKNESSES / WATCHOUTS',response.analysis?.watchouts||[],'watchouts');
    syncAIModal();
  }catch(e){
    console.error(e);
    $('aiStatus').textContent='Unable to generate AI analysis.';
    $('pmeta').textContent='Player profile unavailable.';
    $('insights').innerHTML=`<div class="finding"><strong>AI analysis failed</strong><span>${esc(e.message)}</span></div>`;
    syncAIModal();
  }
}

async function loadPlayer(id,refreshFilters=true){
  playerId=id;clearAI();setLoading(true,'Loading player data…');
  try{
    if(refreshFilters) await loadPlayerFilters(id);
    const x=await get(`/api/player/${id}/overview?${params()}`);
    render(x);setLoading(false);loadAIAnalysis(id);
  }catch(e){
    setLoading(false);console.error(e);
    $('insights').innerHTML=`<div class="finding"><strong>Unable to load player</strong><span>${esc(e.message)}</span></div>`;
    $('aiStatus').textContent='Player data could not be loaded.'
  }
}

let searchTimer;
$('search').addEventListener('input',e=>{
  clearTimeout(searchTimer);
  const q=e.target.value.trim();
  if(!q){$('suggestions').classList.remove('show');return}
  searchTimer=setTimeout(async()=>{
    try{
      const ps=await get('/api/players?q='+encodeURIComponent(q));
      $('suggestions').innerHTML=ps.map(p=>`<div class="suggestion" data-id="${p.player_id}" data-name="${esc(p.player_name)}"><b>${esc(p.player_name)}</b></div>`).join('')||'<div class="suggestion"><span>No players found</span></div>';
      $('suggestions').classList.add('show');
      document.querySelectorAll('.suggestion[data-id]').forEach(el=>el.onclick=async()=>{
        const id=el.dataset.id,name=el.dataset.name;
        $('search').value=name;$('suggestions').classList.remove('show');await loadPlayer(id)
      })
    }catch(err){console.error(err)}
  },180)
});
document.addEventListener('click',e=>{if(!e.target.closest('.searchbox'))$('suggestions').classList.remove('show')});
$('refreshAI').onclick=()=>playerId&&loadAIAnalysis(playerId);
$('maximizeAI').onclick=()=>{syncAIModal();$('aiModal').classList.add('show')};
$('closeAIModal').onclick=()=>$('aiModal').classList.remove('show');
$('aiModal').addEventListener('click',e=>{if(e.target===$('aiModal'))$('aiModal').classList.remove('show')});

document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  if(b.id==='aiInsightsTab'){
    $('aiInsightsSection')?.scrollIntoView({behavior:'smooth',block:'start'});
  }
});

async function downloadInteractiveHTML(){
  if(!playerId){alert('Select a player before downloading the dashboard.');return;}
  const btn=$('downloadBtn');
  const original=btn.innerHTML;
  btn.disabled=true;btn.textContent='Preparing HTML…';
  try{
    const [cssText,jsText]=await Promise.all([
      fetch('/static/style.css').then(r=>{if(!r.ok)throw Error('Unable to load dashboard styles');return r.text()}),
      fetch('/static/app.js').then(r=>{if(!r.ok)throw Error('Unable to load dashboard scripts');return r.text()})
    ]);
    const clone=document.documentElement.cloneNode(true);
    const oldLink=clone.querySelector('link[href="/static/style.css"]');
    if(oldLink){const style=clone.ownerDocument.createElement('style');style.textContent=cssText;oldLink.replaceWith(style)}
    const oldScript=clone.querySelector('script[src="/static/app.js"]');
    if(oldScript)oldScript.remove();
    const dataScript=clone.ownerDocument.createElement('script');
    dataScript.textContent=`window.__CRICKET_EXPORT_DATA__=${JSON.stringify(window.__CRICKET_CURRENT_DATA__||{}).replace(/</g,'\\u003c')};`;
    const exportBody=clone.querySelector('body');
    if(!exportBody) throw Error('Unable to prepare the exported document body');
    exportBody.appendChild(dataScript);
    const appScript=clone.ownerDocument.createElement('script');
    appScript.textContent=jsText;
    exportBody.appendChild(appScript);
    const html='<!doctype html>\n'+clone.outerHTML;
    const blob=new Blob([html],{type:'text/html;charset=utf-8'});
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');
    const safeName=(document.getElementById('pname')?.textContent||'player').trim().replace(/[^a-z0-9]+/gi,'_').replace(/^_|_$/g,'');
    a.href=url;a.download=`Cricket_Intelligence_${safeName||'dashboard'}.html`;document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){
    console.error(e);alert(`Unable to create the HTML download: ${e.message}`);
  }finally{btn.disabled=false;btn.innerHTML=original}
}

async function sendChatQuestion(){
  const input=$('chatInput'), box=$('chatMessages'), btn=$('chatSend');
  const q=(input.value||'').trim(); if(!q)return;
  const empty=box.querySelector('.chat-empty'); if(empty)empty.remove();
  box.insertAdjacentHTML('beforeend',`<div class="chat-msg user"><div class="chat-bubble">${esc(q).replace(/\n/g,'<br>')}</div></div>`);
  input.value=''; btn.disabled=true;
  const loading=document.createElement('div'); loading.className='chat-msg bot'; loading.innerHTML='<div class="chat-bubble chat-loading"><span class="spinner"></span> Searching the IPL knowledge base…</div>'; box.appendChild(loading); box.scrollTop=box.scrollHeight;
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,player_id:playerId,player_name:$('pname')?.textContent||''})});
    const data=await r.json(); if(!r.ok||data.success===false)throw Error(data.error||'Unable to get a response');
    loading.innerHTML=`<div class="chat-bubble">${esc(data.answer||'No answer found.').replace(/\n/g,'<br>')}</div>`;
  }catch(e){loading.innerHTML=`<div class="chat-bubble chat-error">${esc(e.message||'Unable to get a response.')}</div>`}
  finally{btn.disabled=false;input.focus();box.scrollTop=box.scrollHeight}
}
$('chatbotBtn').onclick=()=>{ $('chatModal').classList.add('show'); $('chatInput').focus(); };
$('closeChatModal').onclick=()=>$('chatModal').classList.remove('show');
$('chatModal').addEventListener('click',e=>{if(e.target===$('chatModal'))$('chatModal').classList.remove('show')});
$('chatSend').onclick=sendChatQuestion;
$('chatInput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChatQuestion()}});

$('downloadBtn').onclick=downloadInteractiveHTML;
setupChartMaximize();
setupTableMaximize();

(async()=>{
  if(window.__CRICKET_EXPORT_DATA__){
    window.__CRICKET_CURRENT_DATA__=window.__CRICKET_EXPORT_DATA__;
    makeCharts(window.__CRICKET_EXPORT_DATA__);
    $('downloadBtn')?.remove();
    $('search')?.setAttribute('placeholder','Interactive exported dashboard');
    return;
  }
  initHeaderFilters(); renderHeaderFilters();
})();
