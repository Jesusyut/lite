// app.js — cleaned up (single declarations, single loadTopPicks, NFL/MLB working)

let currentLeague = "mlb";
let selectedMlb = null; // {id, name}
let selectedNfl = null; // {id, name}

const tabsEl     = document.getElementById("tabs");
const playerEl   = document.getElementById("player");
const propEl     = document.getElementById("prop");
const americanEl = document.getElementById("american");
const evalBtn    = document.getElementById("evalBtn");
const topBtn     = document.getElementById("topBtn");
const resultsEl  = document.getElementById("results");
const countEl    = document.getElementById("count");
const loadingEl  = document.getElementById("loading");

function setLoading(v){ if(loadingEl) loadingEl.style.display = v ? "flex" : "none"; }
function setCount(n){ if(countEl) countEl.textContent = String(n); }
function clearResults(){ resultsEl.innerHTML = ""; setCount(0); }
function pct(x){ return (100*(+x||0)).toFixed(1)+'%'; }

// Robust JSON fetch: turns HTML 500 pages into thrown errors we can render.
async function fetchJSON(url, opts){
  const res = await fetch(url, opts);
  let data;
  try { data = await res.json(); }
  catch { throw new Error(`HTTP ${res.status}`); } // backend returned HTML not JSON
  if (!res.ok || (data && data.error)) {
    throw new Error(data?.error || `HTTP ${res.status}`);
  }
  return data;
}

function addResultCard({title, subtitle, pTrend, breakEven, tag}) {
  const card = document.createElement("div");
  card.className = "card";
  const beTxt = (breakEven == null) ? "No price" : `Break-even: ${(breakEven*100).toFixed(1)}%`;
  const tagColor = tag === "Straight" ? "background:#1e9d59"
                  : tag === "Parlay leg" ? "background:#7c6dff"
                  : "background:#2b3245;color:#cbd3ee";
  card.innerHTML = `
    <div class="row">
      <div>
        <div style="font-weight:700">${title}
          <span class="edge-badge" style="${tagColor}">${tag}</span>
        </div>
        <div class="muted small">${subtitle}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:22px;font-weight:700">${(pTrend*100).toFixed(1)}%</div>
        <div class="muted small">${beTxt}</div>
      </div>
    </div>`;
  resultsEl.appendChild(card);
  setCount(resultsEl.children.length);
}

function sparkSVG(arr){
  const w = 120, h = 26;
  const n = Array.isArray(arr) ? arr.length : 0;
  if(n === 0) return '';
  const step = w / Math.max(1, n);
  let rects = '';
  for(let i=0;i<n;i++){
    const v = arr[i] ? 1 : 0;
    const barH = v ? 18 : 6;
    const y = h - barH - 3;
    const x = i * step + 2;
    const barW = Math.max(2, step - 4);
    rects += `<rect x="${x.toFixed(1)}" y="${y}" width="${barW.toFixed(1)}" height="${barH}" rx="2" ry="2" fill="${v ? '#2dd36f' : '#2b3245'}"></rect>`;
  }
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-label="last 10 sparkline">${rects}</svg>`;
}

function addTopCard(pick){
  const propLabel = pick.prop === "HITS_0_5" ? "Over 0.5 Hits" : "Over 1.5 Total Bases";
  const title = `${pick.player_name} — ${propLabel}`;
  const subtitle = [
    `Line ${Number(pick.line).toFixed(1)}`,
    `Trend ${(pick.p_trend*100).toFixed(1)}%`,
    `Break-even ${(pick.break_even_prob*100).toFixed(1)}%`,
    `Edge ${(pick.edge*100).toFixed(1)}%`
  ].join(" • ");
  const svg = sparkSVG(pick.spark || []);

  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="row">
      <div>
        <div style="font-weight:700">${title}
          <span class="edge-badge">${pick.tag}</span>
        </div>
        <div class="muted small">${subtitle}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:22px;font-weight:700">${(pick.p_trend*100).toFixed(1)}%</div>
        <div class="muted small">FD ${pick.american > 0 ? '+'+pick.american : pick.american}</div>
      </div>
    </div>
    <div class="muted small" style="margin-top:8px;display:flex;align-items:center;gap:8px">
      <span>Last 10</span>${svg}
    </div>
    <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="tab" data-act="use">Use in evaluator</button>
    </div>
  `;

  // Wire "Use in evaluator"
  const btn = card.querySelector('button[data-act="use"]');
  btn.addEventListener("click", ()=>{
    // force MLB tab active
    for(const b of tabsEl.querySelectorAll(".tab")) {
      if (b.dataset.league === "mlb") b.classList.add("active"); else b.classList.remove("active");
    }
    currentLeague = "mlb";
    setPropOptions(currentLeague);

    selectedMlb = { id: pick.player_id, name: pick.player_name };
    playerEl.value = pick.player_name;
    propEl.value = pick.prop;
    americanEl.value = pick.american ?? "";

    window.scrollTo({top:0,behavior:"smooth"});
  });

  resultsEl.appendChild(card);
  setCount(resultsEl.children.length);
}

function setPropOptions(league){
  propEl.innerHTML = "";
  const opts = league === "mlb"
    ? [
        ["HITS_0_5","MLB: Over 0.5 Hits"],
        ["TB_1_5","MLB: Over 1.5 Total Bases"],
      ]
    : [
        ["REC","NFL: Receptions (FD line)"],
        ["RUSH_YDS","NFL: Rushing Yards (FD line)"],
        ["REC_YDS","NFL: Receiving Yards (FD line)"],
        ["PASS_YDS","NFL: Passing Yards (FD line)"],
      ];
  for (const [val, label] of opts){
    const o = document.createElement("option");
    o.value = val; o.textContent = label; propEl.appendChild(o);
  }
  playerEl.placeholder = league === "mlb"
    ? "Search MLB player (type 3+ chars)"
    : "Enter NFL player (exact name or search if available)";
}

// Tab click handler (single binding)
tabsEl.addEventListener("click", (e)=>{
  const btn = e.target.closest(".tab");
  if(!btn || btn.disabled) return;
  for(const b of tabsEl.querySelectorAll(".tab")) b.classList.remove("active");
  btn.classList.add("active");
  currentLeague = btn.dataset.league;
  selectedMlb = null; selectedNfl = null;
  clearResults();
  setPropOptions(currentLeague);
});

// MLB search (debounced)
let searchTimer = null;
playerEl.addEventListener("input", ()=>{
  const q = playerEl.value.trim();
  if(currentLeague !== "mlb"){
    selectedNfl = null;
    return;
  }
  if(q.length < 3){ selectedMlb = null; return; }
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(async ()=>{
    try{
      const res = await fetch(`/api/mlb/search?q=${encodeURIComponent(q)}`).then(r=>r.json());
      if(res && res.length){
        selectedMlb = res[0];
        playerEl.value = res[0].name;
      }
    }catch(_){}
  }, 250);
});

// Optional NFL search (on change)
async function tryNflSearchByName(q){
  try{
    const res = await fetch(`/api/nfl/player/search?q=${encodeURIComponent(q)}`).then(r=>r.json());
    if(Array.isArray(res) && res.length){
      selectedNfl = res[0];
      playerEl.value = res[0].name;
    } else {
      selectedNfl = null;
    }
  }catch(_){
    selectedNfl = null;
  }
}
playerEl.addEventListener("change", async ()=>{
  if(currentLeague === "nfl"){
    const q = playerEl.value.trim();
    if(q.length >= 3){
      await tryNflSearchByName(q);
    }
  }
});

// Evaluate
evalBtn.addEventListener("click", async ()=>{
  clearResults();

  const prop = propEl.value;
  const americanRaw = americanEl.value.trim();
  const american = americanRaw ? Number(americanRaw) : null;
  const payload = { league: currentLeague, prop, american };

  let title = "";
  if(currentLeague === "mlb"){
    if(!selectedMlb){
      addResultCard({title:"Error", subtitle:"Pick an MLB player (type to search)", pTrend:0, breakEven:null, tag:"Fade"});
      return;
    }
    payload.player_id = selectedMlb.id;
    payload.player_name = selectedMlb.name; // for FD odds lookup
    title = `${selectedMlb.name} — ${prop.includes("HITS") ? "Over 0.5 Hits" : "Over 1.5 Total Bases"}`;
  } else {
    const name = playerEl.value.trim();
    if(selectedNfl){ payload.player_id = selectedNfl.id; payload.player_name = selectedNfl.name; title = `${selectedNfl.name}`; }
    else if(name){ payload.player_name = name; title = name; }
    else {
      addResultCard({title:"Error", subtitle:"Enter NFL player name", pTrend:0, breakEven:null, tag:"Fade"});
      return;
    }
    const pretty = { REC:"Receptions", RUSH_YDS:"Rushing Yards", REC_YDS:"Receiving Yards", PASS_YDS:"Passing Yards" };
    title += ` — ${pretty[prop] || prop}`;
  }

  setLoading(true);
  try{
    const data = await fetchJSON("/api/evaluate", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });

    const parts = [];
    if (data.used_line != null) parts.push(`Line ${Number(data.used_line).toFixed(1)}`);
    parts.push(`Trend ${(data.p_trend*100).toFixed(1)}%`);
    if (data.break_even_prob != null) parts.push(`Break-even ${(data.break_even_prob*100).toFixed(1)}%`);

    addResultCard({
      title,
      subtitle: parts.join(" • "),
      pTrend: data.p_trend || 0,
      breakEven: data.break_even_prob,
      tag: data.tag || "Fade"
    });
  }catch(err){
    addResultCard({title:"Error", subtitle:String(err.message||err), pTrend:0, breakEven:null, tag:"Fade"});
  }finally{
    setLoading(false);
  }
});

// ---------- Top Picks ----------

const num = (v, d) => { const n = Number(v); return Number.isFinite(n) ? n : d; };
const leaguePath = l => ({ mlb:'mlb', nfl:'nfl', nba:'nba', nhl:'nhl', ufc:'ufc' }[(l||'mlb').toLowerCase()] || 'mlb');

function getFilters(){
  const limit     = num(document.querySelector('#limit')?.value, 12);
  const min_edge  = num(document.querySelector('#min-edge')?.value, 0.03);
  const min_trend = num(document.querySelector('#min-trend')?.value, 0.57);
  const events    = num(document.querySelector('#events')?.value, 10);
  return { limit, min_edge, min_trend, events };
}

// uses the active league (single definition)
async function loadTopPicks(){
  clearResults();
  setLoading(true);
  try{
    const qs   = new URLSearchParams(getFilters()).toString();
    const path = `/api/top/${leaguePath(currentLeague)}?${qs}`;
    const res  = await fetchJSON(path);
    const list = Array.isArray(res) ? res : (res?.data ?? []);
    if (list.length) list.forEach(addTopCard);
    else addResultCard({
      title:"No picks",
      subtitle:`No positive-edge ${String(currentLeague).toUpperCase()} props under current filters.`,
      pTrend:0, breakEven:null, tag:"Fade"
    });
  }catch(err){
    addResultCard({ title:"Error", subtitle:String(err.message||err), pTrend:0, breakEven:null, tag:"Fade" });
  }finally{
    setLoading(false);
  }
}


// Wire once
topBtn?.addEventListener('click', loadTopPicks);

// Hide spinner on initial load + auto-load Top Picks (MLB)
document.addEventListener('DOMContentLoaded', () => {
  setLoading(false);
  loadTopPicks();              // ← loads Top Picks by default
});
// in app.js, right after DOMContentLoaded auto-load:
document.addEventListener('DOMContentLoaded', () => {
  setLoading(false);
  loadTopPicks();
  // auto-retry once after a short delay to pick up warmed cache
  setTimeout(() => loadTopPicks(), 3500);
});

