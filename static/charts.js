/* ==========================================================================
   charts.js — Chart.js theming, the HTML building blocks (bar lists, stat tiles,
   hero, stacked meters), the table-view twin every chart carries, and the
   calendar + heatmap SVGs. Marks are thin, grids are hairlines, stacked segments
   carry a 2px surface gap, and identity is never colour-alone.
   ========================================================================== */
const charts = {};
const toolPointStyles = {};
function toolPointStyle(source){
  if(!SRC[source] || typeof Image==='undefined') return 'circle';
  if(!toolPointStyles[source]){
    const canvas=document.createElement('canvas'),image=new Image();
    canvas.width=canvas.height=16;
    image.onload=()=>{
      const ctx=canvas.getContext('2d');
      ctx.fillStyle='#fff';ctx.fillRect(0,0,16,16);ctx.drawImage(image,1,1,14,14);
      Object.values(charts).forEach(chart=>chart.update('none'));
    };
    image.src='/static/tool-icons/'+SRC[source].icon+'.svg';
    toolPointStyles[source]=canvas;
  }
  return toolPointStyles[source];
}

function theme(){
  return {
    text:cssv("--text"), text2:cssv("--text-2"), text3:cssv("--text-3"), grid:cssv("--grid"),
    surface:cssv("--surface"), border:cssv("--border-2"), ink:cssv("--bar"),
  };
}
/* cfg.$fmt formats values for the tooltip and the table twin; cfg.$stacked adds a
   Total column to the twin; cfg.$xLabel names its first column. */
function mk(id, cfg){
  const el = document.getElementById(id);
  if(!el) return;
  if(charts[id]) charts[id].destroy();
  const T = theme();
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 11;
  Chart.defaults.color = T.text3;
  cfg.options = cfg.options || {};
  cfg.options.responsive = true;
  cfg.options.maintainAspectRatio = false;
  cfg.options.animation = {duration:200};
  cfg.options.plugins = deepMerge({
    legend:{display:false},
    tooltip:{
      backgroundColor:T.surface, titleColor:T.text, bodyColor:T.text2, footerColor:T.text,
      borderColor:T.border, borderWidth:1, padding:10, cornerRadius:10,
      displayColors:true, boxWidth:8, boxHeight:8, boxPadding:4,
      titleFont:{weight:"600",size:12}, bodyFont:{size:12}, footerFont:{weight:"600",size:12},
      usePointStyle:true, itemSort:(a,b)=>b.parsed.y-a.parsed.y,
      callbacks:{labelPointStyle:ctx=>({pointStyle:ctx.dataset.source?toolPointStyle(ctx.dataset.source):'circle',rotation:0})},
    }
  }, cfg.options.plugins||{});
  // Stacked areas: each band fills down to the series beneath it, not to zero —
  // filling every band to the origin piles translucent washes into a muddy grey.
  if(cfg.type === "line"){
    let first = true;
    for(const x of (cfg.data.datasets||[])){
      if(x.stack !== "a" || x.fill === false) continue;
      x.fill = first ? "origin" : "-1"; first = false;
    }
  }
  const {$fmt, $stacked, $xLabel} = cfg;
  delete cfg.$fmt; delete cfg.$stacked; delete cfg.$xLabel;
  charts[id] = new Chart(el, cfg);
  Object.assign(charts[id], {$fmt, $stacked, $xLabel});
  applyTableView(id);
  return charts[id];
}
function axes(o){
  const T = theme();
  const base = {
    x:{grid:{display:false},border:{display:false},
       ticks:{color:T.text3,font:{size:11},maxRotation:0,autoSkipPadding:16}},
    y:{grid:{color:T.grid},border:{display:false},
       ticks:{color:T.text3,font:{size:11},padding:6,maxTicksLimit:6}},
  };
  return deepMerge(base, o||{});
}
function deepMerge(a,b){
  const out=Object.assign({},a);
  for(const k in b){
    out[k] = (b[k] && typeof b[k]==="object" && !Array.isArray(b[k]))
      ? deepMerge(a[k]||{}, b[k]) : b[k];
  }
  return out;
}
/* stacked-bar dataset with the mandated 2px surface gap between segments */
function stackDS(label, data, color, source){
  return {label, data, source, backgroundColor:color, stack:"a",
    borderColor:cssv("--surface"), borderWidth:{top:2,left:0,right:0,bottom:0},
    borderRadius:3, borderSkipped:false, maxBarThickness:24};
}
/* A line needs TWO points to draw a segment, so a single-day range (or a series
   with one lone reading) renders as empty axes. Show the point itself instead. */
function soloPoint(data){
  return (data||[]).filter(v=>v!=null && v!==undefined).length < 2 ? 4 : 0;
}
function areaDS(label, data, color, fill, source){
  return {label, data, source, borderColor:color, backgroundColor:color+"26",
    borderWidth:2, pointRadius:soloPoint(data), pointHoverRadius:4, tension:.25,
    fill:fill===undefined?true:fill, stack:"a"};
}

/* ---------- table twin: every chart can be read without the chart ---------- */
function chartTable(id){
  const c = charts[id]; if(!c) return "";
  const fmt = c.$fmt || fmtNum, labels = c.data.labels || [], ds = c.data.datasets || [];
  const total = c.$stacked && ds.length > 1;
  let h = `<table><thead><tr><th class="nosort">${esc(c.$xLabel||"Day")}</th>${
    ds.map(d=>`<th class="r nosort">${d.source?toolLabel(d.source):esc(d.label||"")}</th>`).join("")}${
    total?'<th class="r nosort">Total</th>':""}</tr></thead><tbody>`;
  labels.forEach((l,i)=>{
    let tot = 0;
    h += `<tr><td>${esc(l)}</td>` + ds.map(d=>{
      const v = d.data[i];
      if(v!=null) tot += +v || 0;
      return `<td class="r">${v==null?'<span class="dim">—</span>':fmt(+v)}</td>`;
    }).join("") + (total?`<td class="r"><b>${fmt(tot)}</b></td>`:"") + `</tr>`;
  });
  return h + "</tbody></table>";
}
function applyTableView(id){
  const tv = document.getElementById("tv-"+id); if(!tv) return;
  const on = S.tableView.has(id);
  const canvas = document.getElementById(id), box = canvas && canvas.parentElement;
  const btn = document.querySelector(`.tv[data-tv="${id}"]`);
  if(btn){ btn.classList.toggle("on", on); btn.title = on ? "Show as chart" : "Show as table"; }
  tv.hidden = !on;
  if(box) box.style.display = on ? "none" : "";
  tv.innerHTML = on ? chartTable(id) : "";
}

/* ---------- HTML building blocks ---------- */
function toolDot(s){
  return toolIcon(s);
}
/* A ranked list with inline bars — easier to read than a horizontal bar chart,
   and the numbers are text, so nothing is gated behind a tooltip.
   row: {label, value, color? (swatch + bar), barColor?, dots? [sources], title?, attr?} */
function barList(el, rows, o){
  o = o || {};
  if(typeof el === "string") el = document.getElementById(el);
  if(!el) return;
  const fmt = o.fmt || fmtTok;
  rows = rows.filter(r => (r.value||0) > 0 || o.keepZero);
  if(!rows.length){ el.innerHTML = `<div class="empty">${esc(o.empty||"Nothing in range.")}</div>`; return; }
  const total = o.total != null ? o.total : rows.reduce((a,r)=>a+(r.value||0),0);
  const max = Math.max(...rows.map(r=>r.value||0), 1e-12);
  const shown = rows.slice(0, o.limit || rows.length), rest = rows.length - shown.length;
  el.innerHTML = `<div class="bars">` + shown.map(r=>{
    const w = r.value > 0 ? Math.max(1.5, r.value/max*100) : 0;
    const lead = r.source ? toolIcon(r.source,true) : r.color ? `<span class="sw" style="background:${r.color}"></span>` : "";
    const dots = r.dots && r.dots.length ? `<span class="dots">${r.dots.map(toolDot).join("")}</span>` : "";
    const share = o.share === false || !total ? "" : `<span>${fmtPct((r.value||0)/total)}</span>`;
    const bar = r.barColor || r.color;
    return `<div class="bar-row${r.attr?" click":""}"${r.attr?" "+r.attr:""}>
      <div class="bar-name">${lead}${r.sub?`<span class="stack"><span class="t" title="${esc(r.title||r.label)}">${esc(r.label)}</span><span class="bar-sub">${esc(r.sub)}</span></span>`
        :`<span class="t" title="${esc(r.title||r.label)}">${esc(r.label)}</span>`}${dots}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${w.toFixed(2)}%${bar?";background:"+bar:""}"></div></div>
      <div class="bar-val"><b>${fmt(r.value||0)}</b>${share}</div></div>`;
  }).join("") + `</div>` + (rest > 0 ? `<div class="bar-more">+ ${fmtNum(rest)} more${o.more?" · "+o.more:""}</div>` : "");
}
/* tile: {l, v (html), d (delta html), s (text), spark (svg), title} */
function tilesHTML(items){
  return items.filter(Boolean).map(t=>`<div class="tile"${t.title?` title="${esc(t.title)}"`:""}>
      <div class="l">${esc(t.l)}</div><div class="v">${t.v}</div>
      <div class="foot"><span class="s">${t.d||""}${t.d&&t.s?" · ":""}${t.source?toolIcon(t.source,true)+" ":""}${t.s?esc(t.s):""}</span>${t.spark?`<span class="spark">${t.spark}</span>`:""}</div>
    </div>`).join("");
}
function heroHTML(o){
  return `<div class="hero-label">${esc(o.label)}</div>
    <div class="hero-value-row"><div class="hero-value">${o.value}</div>${
      o.secondary?`<div class="hero-secondary" title="${esc(o.secondary.title||"")}"><div class="hero-secondary-label">${esc(o.secondary.label)}</div><div class="hero-secondary-value">${o.secondary.value}</div></div>`:""}</div>
    <div class="hero-delta">${o.delta||""}${o.note?`<span>${esc(o.note)}</span>`:""}</div>
    ${o.feature?`<div class="hero-feature" title="${esc(o.feature.title||"")}">
      <div><div class="hero-feature-label">${esc(o.feature.label)}</div><div class="hero-feature-value">${o.feature.value}</div></div>
      ${o.feature.spark?`<div class="hero-feature-spark">${o.feature.spark}</div>`:""}</div>`:""}
    ${o.facts && o.facts.length ? `<div class="hero-facts">${o.facts.map(f=>
      `<div title="${esc(f.title||"")}"><div class="f-l">${esc(f.l)}</div><div class="f-v">${f.v}</div></div>`).join("")}</div>` : ""}`;
}
/* Part-to-whole per row, normalised to 100% — the 2px gaps separate segments. */
function stackMeters(el, rows, kinds, fmt){
  if(typeof el === "string") el = document.getElementById(el);
  if(!rows.length){ el.innerHTML = `<div class="empty">Nothing in range.</div>`; return; }
  el.innerHTML = `<div class="legend">${kinds.map(k=>`<span class="li static"><span class="sw" style="background:${k.color}"></span>${esc(k.label)}</span>`).join("")}</div>`
    + rows.map(r=>{
      const tot = kinds.reduce((a,k)=>a+(r.parts[k.key]||0),0) || 1;
      return `<div style="margin:12px 0 2px">
        <div style="display:flex;justify-content:space-between;gap:10px;font-size:12.5px;margin-bottom:6px">
          <span style="display:flex;align-items:center;gap:7px"><span class="sw" style="background:${r.color}"></span>${r.source?toolLabel(r.source):esc(r.label)}</span>
          <span class="num"><b>${fmt(tot)}</b></span></div>
        <div class="meter" role="img" aria-label="${esc(r.label)}: ${kinds.map(k=>k.label+" "+fmtPct((r.parts[k.key]||0)/tot)).join(", ")}">${
          kinds.filter(k=>r.parts[k.key]>0).map(k=>`<i style="width:${((r.parts[k.key]||0)/tot*100).toFixed(2)}%;background:${k.color}" title="${esc(k.label)}: ${fmt(r.parts[k.key])} (${fmtPct(r.parts[k.key]/tot)})"></i>`).join("")}</div>
      </div>`;
    }).join("");
}

/* ---------- activity calendar (SVG, sequential blue) ---------- */
function renderCalendar(byDay, maxV, onClick){
  const wrap = document.getElementById("calWrap");
  const end = new Date(); end.setHours(0,0,0,0);
  const start = new Date(end); start.setDate(start.getDate()-364);
  start.setDate(start.getDate()-((start.getDay()+6)%7));      // back to Monday
  const weeks=[]; let cur=new Date(start);
  while(cur<=end){ const wk=[]; for(let i=0;i<7;i++){ wk.push(new Date(cur)); cur.setDate(cur.getDate()+1); } weeks.push(wk); }
  // The calendar shares a row with Monthly rhythm on desktop. At compact desktop
  // widths it keeps all 12 months visible instead of becoming a cropped scroller.
  const mT=18, mL=28;
  const step=Math.max(6, Math.min(21, Math.floor(((wrap.clientWidth||800)-mL-8)/weeks.length)));
  const gap=step<12?2:3, compact=step<12;
  const cell=step-gap;
  const ramp = seqRamp();
  const bucket = v => { if(!v) return ramp[0];
    const q=v/(maxV||1);
    return q>.6?ramp[6]:q>.3?ramp[5]:q>.12?ramp[4]:q>.03?ramp[2]:ramp[1]; };
  const W = mL+weeks.length*step+8, H = mT+7*step+6;
  let s=`<svg width="${W}" height="${H}" role="img" aria-label="activity calendar">`;
  let lastM=-1;
  weeks.forEach((wk,wi)=>{ const m=wk[0].getMonth();
    if(m!==lastM){ lastM=m;
      s+=`<text x="${mL+wi*step}" y="10" fill="${cssv("--text-3")}" font-size="10.5">${compact?MONTHS[m][0]:MONTHS[m]}</text>`; }});
  [["Mon",0],["Wed",2],["Fri",4]].forEach(([l,r])=>{
    s+=`<text x="0" y="${mT+r*step+10}" fill="${cssv("--text-3")}" font-size="10">${l}</text>`; });
  weeks.forEach((wk,wi)=>wk.forEach((d,di)=>{
    if(d>end) return;
    const k=dkey(d), v=byDay[k]||0;
    s+=`<rect x="${mL+wi*step}" y="${mT+di*step}" width="${cell}" height="${cell}" rx="3"
        fill="${bucket(v)}" data-day="${k}" data-v="${v}" style="cursor:pointer"/>`;
  }));
  s+="</svg>";
  wrap.innerHTML=s;
  const svg=wrap.querySelector("svg");
  svg.addEventListener("mousemove",e=>{
    const r=e.target.closest("rect"); if(!r) return hideTip();
    const v=+r.dataset.v;
    showTip(`<div class="t">${r.dataset.day}</div><div class="r"><span class="k">tokens</span>
      <span class="v">${v?fmtTok(v):"none"}</span></div>`, e.clientX, e.clientY);
  });
  svg.addEventListener("mouseleave",hideTip);
  svg.addEventListener("click",e=>{ const r=e.target.closest("rect"); if(r&&onClick) onClick(r.dataset.day); });
}

/* ---------- compact month bars paired with the activity calendar ---------- */
function renderMonthlyRhythm(points, onClick){
  const wrap=document.getElementById("monthlyRhythm"); if(!wrap) return;
  if(!points.length){ wrap.innerHTML=`<div class="empty">No activity in the last 12 months.</div>`; return; }
  const W=360, H=116, mT=6, mL=2, mR=2, mB=20, base=H-mB;
  const plotH=base-mT, max=Math.max(...points.map(p=>p.value||0),1);
  const step=(W-mL-mR)/points.length, barW=Math.max(3,step-5);
  let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="monthly token activity; click a month to filter the dashboard">`;
  s+=`<line class="month-axis" x1="${mL}" y1="${base}" x2="${W-mR}" y2="${base}"/>`;
  points.forEach((p,i)=>{
    const h=p.value ? Math.max(3,p.value/max*plotH) : 2;
    const x=mL+i*step+(step-barW)/2, y=base-h;
    const state=`${p.current?" current":""}${p.selected?" selected":""}`;
    s+=`<rect class="month-bar${state}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barW.toFixed(2)}" height="${h.toFixed(2)}" rx="2"
      data-index="${i}" role="button" tabindex="0" aria-label="${esc(p.title)}: ${fmtTok(p.value)} tokens. Filter to this month."/>
      <text class="month-label" x="${(x+barW/2).toFixed(2)}" y="${H-5}" text-anchor="middle">${esc(p.label)}</text>`;
  });
  s+="</svg>";
  wrap.innerHTML=s;
  const svg=wrap.querySelector("svg");
  const pointFor=target=>{ const bar=target.closest(".month-bar"); return bar&&points[+bar.dataset.index]; };
  const activate=target=>{ const point=pointFor(target); if(point&&onClick) onClick(point); };
  svg.addEventListener("mousemove",e=>{
    const point=pointFor(e.target); if(!point) return hideTip();
    showTip(`<div class="t">${esc(point.title)}</div><div class="r"><span class="k">tokens</span><span class="v">${fmtTok(point.value)}</span></div>`,e.clientX,e.clientY);
  });
  svg.addEventListener("mouseleave",hideTip);
  svg.addEventListener("click",e=>activate(e.target));
  svg.addEventListener("keydown",e=>{
    if(e.key!=="Enter"&&e.key!==" ") return;
    if(!pointFor(e.target)) return;
    e.preventDefault(); activate(e.target);
  });
}

/* ---------- hour x weekday heatmap (SVG, sequential blue) ---------- */
function fmtHour12(hour){
  const value = Number(hour) % 24;
  return `${value % 12 || 12} ${value < 12 ? "AM" : "PM"}`;
}

function renderHeatmap(cells, maxV){
  const gap=2, rowH=22, mL=34, mT=16;
  const ramp=seqRamp();
  const bucket=v=>{ if(!v) return ramp[0]; const q=v/(maxV||1);
    return q>.66?ramp[6]:q>.4?ramp[5]:q>.2?ramp[4]:q>.07?ramp[3]:q>.01?ramp[2]:ramp[1]; };
  const W=760, H=mT+7*rowH+14, cellW=(W-mL)/24;
  let s=`<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMinYMin meet" role="img" aria-label="activity by hour and weekday">`;
  for(let h=0;h<24;h+=3)
    s+=`<text x="${mL+h*cellW}" y="10" fill="${cssv("--text-3")}" font-size="10">${fmtHour12(h)}</text>`;
  for(let d=0;d<7;d++){
    s+=`<text x="0" y="${mT+d*rowH+15}" fill="${cssv("--text-3")}" font-size="10">${DOW[d]}</text>`;
    for(let h=0;h<24;h++){
      const v=(cells[d]&&cells[d][h])||0;
      s+=`<rect x="${mL+h*cellW}" y="${mT+d*rowH}" width="${cellW-gap}" height="${rowH-gap}" rx="3"
          fill="${bucket(v)}" data-d="${d}" data-h="${h}" data-v="${v}"/>`;
    }
  }
  s+="</svg>";
  const wrap=document.getElementById("heatmap"); wrap.innerHTML=s;
  const svg=wrap.querySelector("svg");
  svg.addEventListener("mousemove",e=>{
    const r=e.target.closest("rect"); if(!r) return hideTip();
    showTip(`<div class="t">${DOW[+r.dataset.d]} ${fmtHour12(+r.dataset.h)}</div>
      <div class="r"><span class="k">tokens</span><span class="v">${fmtTok(+r.dataset.v)}</span></div>`,
      e.clientX,e.clientY);
  });
  svg.addEventListener("mouseleave",hideTip);
}
