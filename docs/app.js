// Peter 持仓透视 — 叙事式单页看板逻辑
const TOP_N = 8;
const PALETTE = ['#4f46e5','#0ea5e9','#14b8a6','#f59e0b','#e5484d','#8b5cf6','#ec4899','#22c55e'];
const TYPE_LABEL = { buy:'加仓', new:'建仓', sell:'减仓', sold:'清仓' };
const TYPE_UP = { buy:true, new:true, sell:false, sold:false };

function loadJSON(p){
  return fetch(p).then(r=>{ if(!r.ok) throw new Error(p+' -> '+r.status); return r.json(); });
}

function esc(s){ return String(s).replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c])); }

async function init(){
  try{
    const [hist, events, prices] = await Promise.all([
      loadJSON('data/holdings_history.json'),
      loadJSON('data/events.json'),
      loadJSON('data/price_history.json').catch(()=>({})),
    ]);
    const dates = Object.keys(hist).sort();
    const latest = dates[dates.length-1];
    document.getElementById('updated').textContent =
      '持仓 ' + dates.length + ' 天（' + dates[0] + ' ~ ' + latest + '） · 调仓事件 ' + events.length + ' 笔 · 行情标的 ' + Object.keys(prices).length + ' 个';

    // 最新快照的调仓事件（events 里最新日期）
    const evDates = Array.from(new Set(events.map(e=>e.date))).sort();
    const todayDate = evDates.length ? evDates[evDates.length-1] : latest;
    const todayEvents = events.filter(e=>e.date===todayDate);
    const nBuy = todayEvents.filter(e=>e.type==='buy'||e.type==='new').length;
    const nSell = todayEvents.filter(e=>e.type==='sell'||e.type==='sold').length;

    renderVerdict(nBuy, nSell, todayDate);
    renderKpis(nBuy, nSell, hist[latest].length);
    renderTrades(todayEvents);
    renderAllocation(hist[latest]);
    renderNetValue(prices, hist[latest]);
    renderTimeline(events);

    window.addEventListener('resize', ()=>{ if(window._nc) window._nc.resize(); });
  }catch(err){
    document.getElementById('updated').textContent = '数据加载失败：' + err.message + '（请通过 GitHub Pages 访问，勿用 file:// 直接打开）';
  }
}

function renderVerdict(nBuy, nSell, date){
  const v = document.getElementById('verdict');
  const note = document.getElementById('note');
  if(nBuy===0 && nSell===0){
    v.textContent = '最新快照 · 无主动调仓';
    note.textContent = date + '：仓位变动均为市场自然波动，博主未主动买卖。';
  }else{
    const parts = [];
    if(nBuy>0) parts.push('加仓 ' + nBuy + ' 只');
    if(nSell>0) parts.push('减仓 ' + nSell + ' 只');
    v.innerHTML = date + ' · 他 ' + parts.map(p=>{
      const up = p.indexOf('加')===0;
      return '<span class="' + (up?'up':'down') + '">' + esc(p) + '</span>';
    }).join(' · ');
    note.textContent = '已通过算法剥离股价涨跌，只统计博主真实动作。';
  }
}

function renderKpis(nBuy, nSell, total){
  document.getElementById('kpi-buy').textContent = nBuy + ' 只';
  document.getElementById('kpi-sell').textContent = nSell + ' 只';
  document.getElementById('kpi-total').textContent = total + ' 只';
}

function renderTrades(todayEvents){
  const box = document.getElementById('trades');
  const sorted = [...todayEvents].sort((a,b)=>Math.abs(b.active_diff)-Math.abs(a.active_diff));
  if(sorted.length===0){
    box.innerHTML = '<div style="color:var(--sub); font-size:14px; padding:6px 0;">暂无主动调仓</div>';
    return;
  }
  const MAX = 12;
  const shown = sorted.slice(0, MAX);
  let html = shown.map(e=>{
    const up = TYPE_UP[e.type];
    const color = up ? 'var(--up)' : 'var(--down)';
    const bg = up ? 'var(--up-bg)' : 'var(--down-bg)';
    const sign = up ? '+' : '';
    return '<div class="trade"><span class="name">' + esc(e.name) +
      '<span class="code">' + esc(e.code) + '</span></span>' +
      '<span class="tag" style="color:' + color + '; background:' + bg + ';">' +
      TYPE_LABEL[e.type] + ' ' + sign + Math.abs(e.active_diff).toFixed(1) + '%</span></div>';
  }).join('');
  if(sorted.length > MAX){
    html += '<div class="more">…另有 ' + (sorted.length - MAX) + ' 笔，见下方时间轴</div>';
  }
  box.innerHTML = html;
}

function renderAllocation(holdings){
  const box = document.getElementById('allocation');
  const sorted = [...holdings].sort((a,b)=>b.share-a.share);
  const top = sorted.slice(0,6);
  const rest = sorted.slice(6);
  const restSum = rest.reduce((s,x)=>s+x.share,0);
  const maxShare = top.length ? top[0].share : 1;
  let html = top.map(x=>{
    const w = (x.share/maxShare*100).toFixed(1);
    return '<div class="bar-row"><div class="top"><span>' + esc(x.name) +
      '</span><span class="pct num">' + x.share.toFixed(1) + '%</span></div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + w + '%"></div></div></div>';
  }).join('');
  if(rest.length){
    const w = (restSum/maxShare*100).toFixed(1);
    html += '<div class="bar-row"><div class="top"><span>其他 ' + rest.length + ' 只</span>' +
      '<span class="pct num">' + restSum.toFixed(1) + '%</span></div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + w + '%; background:var(--bar-other);"></div></div></div>';
  }
  box.innerHTML = html;
}

function renderNetValue(prices, holdings){
  const box = document.getElementById('netvalue');
  const top = [...holdings].sort((a,b)=>b.share-a.share).slice(0,TOP_N).map(x=>x.code);
  const avail = top.filter(c=>prices[c]);
  if(avail.length===0){
    box.innerHTML = '<div style="height:400px; display:flex; align-items:center; justify-content:center; color:var(--sub);">暂无行情数据</div>';
    return;
  }
  const baseCode = avail[0];
  const xDates = Object.keys(prices[baseCode]).sort();
  const series = avail.map((c,i)=>{
    const sd = prices[c];
    const first = xDates.find(d=>sd[d]!=null);
    const base = sd[first];
    const data = xDates.map(d=> sd[d]!=null ? +(sd[d]/base*100).toFixed(2) : null);
    return { name:c, type:'line', smooth:true, showSymbol:false, lineStyle:{width:1.7},
             itemStyle:{color:PALETTE[i%PALETTE.length]}, emphasis:{focus:'series'}, data };
  });
  window._nc = echarts.init(box);
  window._nc.setOption({
    tooltip:{trigger:'axis', valueFormatter:v=> v==null?'—':v},
    legend:{top:0, textStyle:{color:'#64748b'}},
    grid:{left:46, right:18, top:38, bottom:30},
    xAxis:{type:'category', data:xDates, boundaryGap:false, axisLabel:{color:'#94a3b8', formatter:v=>v.slice(5)}},
    yAxis:{type:'value', scale:true, axisLabel:{color:'#94a3b8'}},
    series,
  });
}

function renderTimeline(events){
  const box = document.getElementById('timeline');
  const sorted = [...events].sort((a,b)=>{
    if(a.date!==b.date) return a.date < b.date ? 1 : -1;
    return Math.abs(b.active_diff)-Math.abs(a.active_diff);
  });
  const recent = sorted.slice(0,30);
  if(recent.length===0){
    box.innerHTML = '<div style="color:var(--sub); font-size:14px;">暂无调仓事件</div>';
    return;
  }
  box.innerHTML = recent.map(e=>{
    const up = TYPE_UP[e.type];
    const cls = up ? 'up' : 'down';
    const color = up ? 'var(--up)' : 'var(--down)';
    const sign = up ? '+' : '';
    return '<div class="event ' + cls + '"><p class="meta">' + e.date + ' · ' + TYPE_LABEL[e.type] + '</p>' +
      '<p class="title">' + esc(e.name) + ' <span class="num" style="color:' + color + ';">' +
      sign + Math.abs(e.active_diff).toFixed(1) + '%</span></p></div>';
  }).join('');
}

init();
