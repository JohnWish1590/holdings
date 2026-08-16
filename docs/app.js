// Peter 持仓透视 — 三视图前端逻辑（纯静态，fetch data/*.json）
const TOP_N = 12;
const PALETTE = ['#6366f1','#0ea5e9','#14b8a6','#f59e0b','#ef4444','#8b5cf6','#ec4899','#22c55e','#eab308','#06b6d4','#a855f7','#f97316'];
const TYPE_COLOR = { buy:'#ef4444', new:'#ef4444', sell:'#10b981', sold:'#10b981' };
const TYPE_LABEL = { buy:'加仓', new:'建仓', sell:'减仓', sold:'清仓', drift:'漂移' };
const charts = {};

function loadJSON(p){
  return fetch(p).then(r=>{ if(!r.ok) throw new Error(p+' -> '+r.status); return r.json(); });
}

function topCodes(hist, n){
  const dates = Object.keys(hist).sort();
  const latest = hist[dates[dates.length-1]] || [];
  return [...latest].sort((a,b)=>b.share-a.share).slice(0,n).map(x=>x.code);
}

function renderTimeline(hist){
  const dates = Object.keys(hist).sort();
  const top = topCodes(hist, TOP_N);
  const seriesData = {};
  top.forEach(c=> seriesData[c]=[]);
  const other = [];
  dates.forEach(d=>{
    const m = {};
    hist[d].forEach(x=> m[x.code]=x.share);
    let otherSum = 0;
    hist[d].forEach(x=>{ if(!top.includes(x.code)) otherSum += x.share; });
    top.forEach(c=>{}); // placeholder
    top.forEach(c=> seriesData[c].push(m[c]!=null? m[c]: null));
    other.push(+otherSum.toFixed(2));
  });
  const nameOf = {};
  dates.forEach(d=> hist[d].forEach(x=> nameOf[x.code]=x.name));

  const series = top.map((c,i)=>({
    name: nameOf[c]||c,
    type:'line', stack:'total', areaStyle:{},
    smooth:true, showSymbol:false, lineStyle:{width:0},
    itemStyle:{color:PALETTE[i%PALETTE.length]},
    emphasis:{focus:'series'},
    data: seriesData[c],
  }));
  series.push({
    name:'其他', type:'line', stack:'total', areaStyle:{},
    smooth:true, showSymbol:false, lineStyle:{width:0},
    itemStyle:{color:'#cbd5e1'}, data: other,
  });

  charts.timeline = echarts.init(document.getElementById('chart-timeline'));
  charts.timeline.setOption({
    tooltip:{trigger:'axis', valueFormatter:v=> v==null?'—':v+'%'},
    legend:{type:'scroll', top:0, textStyle:{color:'#64748b'}},
    grid:{left:48, right:18, top:42, bottom:64},
    xAxis:{type:'category', data:dates, boundaryGap:false, axisLabel:{color:'#94a3b8', formatter:v=>v.slice(5)}},
    yAxis:{type:'value', max:100, axisLabel:{color:'#94a3b8', formatter:'{value}%'}},
    dataZoom:[{type:'inside'},{type:'slider', bottom:14, height:18}],
    series: series,
  });
}

function renderEvents(events){
  const types = ['buy','new','sell','sold'];
  const series = types.map(t=>({
    name: TYPE_LABEL[t],
    type:'scatter',
    data: events.filter(e=>e.type===t).map(e=>[e.date, e.active_diff, e.name, e.code]),
    symbolSize: v=> Math.max(10, Math.min(46, Math.abs(v[1])*3.2)),
    itemStyle:{color:TYPE_COLOR[t], opacity:.82},
    emphasis:{focus:'series'},
  }));
  const xDates = [...new Set(events.map(e=>e.date))].sort();
  charts.events = echarts.init(document.getElementById('chart-events'));
  charts.events.setOption({
    tooltip:{trigger:'item', formatter:p=>{
      const [date, val, name, code]=p.data;
      const color = (p.seriesName==='加仓'||p.seriesName==='建仓')?'#ef4444':'#10b981';
      return `<b>${name}</b> <span style="color:#94a3b8">${code}</span><br/>日期：${date}<br/>${p.seriesName}：<b style="color:${color}">${val>0?'+':''}${val}%</b>`;
    }},
    legend:{top:0, textStyle:{color:'#64748b'}},
    grid:{left:54, right:24, top:42, bottom:68},
    xAxis:{type:'category', data:xDates, axisLabel:{color:'#94a3b8', rotate:45, formatter:v=>v.slice(5)}},
    yAxis:{type:'value', name:'主动调仓 %', nameTextStyle:{color:'#94a3b8'}, axisLabel:{color:'#94a3b8', formatter:'{value}%'}},
    dataZoom:[{type:'inside'},{type:'slider', bottom:16, height:18}],
    series,
  });
}

function renderNetValue(prices, hist){
  const top = topCodes(hist, TOP_N);
  const baseCode = top.find(c=>prices[c]);
  if(!baseCode){
    charts.netvalue = echarts.init(document.getElementById('chart-netvalue'));
    charts.netvalue.setOption({title:{text:'暂无行情数据（将在下次联网抓取后自动生成）', left:'center', top:'center', textStyle:{color:'#94a3b8', fontSize:14}}});
    return;
  }
  const xDates = Object.keys(prices[baseCode]).sort();
  const series = top.filter(c=>prices[c]).map((c,i)=>{
    const sd = prices[c];
    const firstValid = xDates.find(d=>sd[d]!=null);
    const base = sd[firstValid];
    const data = xDates.map(d=> sd[d]!=null ? +(sd[d]/base*100).toFixed(2) : null);
    return { name:c, type:'line', showSymbol:false, lineStyle:{width:1.4},
             itemStyle:{color:PALETTE[i%PALETTE.length]}, emphasis:{focus:'series'}, data };
  });
  charts.netvalue = echarts.init(document.getElementById('chart-netvalue'));
  charts.netvalue.setOption({
    tooltip:{trigger:'axis', valueFormatter:v=> v==null?'—':v},
    legend:{type:'scroll', top:0, textStyle:{color:'#64748b'}},
    grid:{left:48, right:18, top:42, bottom:64},
    xAxis:{type:'category', data:xDates, boundaryGap:false, axisLabel:{color:'#94a3b8', formatter:v=>v.slice(5)}},
    yAxis:{type:'value', scale:true, axisLabel:{color:'#94a3b8'}},
    dataZoom:[{type:'inside'},{type:'slider', bottom:16, height:18}],
    series,
  });
}

function showTab(id){
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('view-'+id).classList.add('active');
  document.querySelector('.tab[data-view="'+id+'"]').classList.add('active');
  if(charts[id]) charts[id].resize();
}

async function init(){
  document.querySelectorAll('.tab').forEach(t=> t.addEventListener('click', ()=>showTab(t.dataset.view)));
  try{
    const [hist, events, prices] = await Promise.all([
      loadJSON('data/holdings_history.json'),
      loadJSON('data/events.json'),
      loadJSON('data/price_history.json').catch(()=>({})),
    ]);
    const dates = Object.keys(hist).sort();
    document.getElementById('meta').textContent =
      `持仓天数：${dates.length} 天（${dates[0]} ~ ${dates[dates.length-1]}） · 调仓事件：${events.length} 笔 · 行情标的：${Object.keys(prices).length} 个`;
    renderTimeline(hist);
    renderEvents(events);
    renderNetValue(prices, hist);
    window.addEventListener('resize', ()=> Object.values(charts).forEach(c=>c.resize()));
    showTab('timeline');
  }catch(err){
    document.getElementById('meta').textContent = '数据加载失败：'+err.message+'（请通过 GitHub Pages 访问，勿用 file:// 直接打开）';
  }
}
init();
