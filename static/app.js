// app.js — Top Picks only

let currentLeague = "mlb";

const tabsEl     = document.getElementById("tabs");
const topBtn     = document.getElementById("topBtn");
const resultsEl  = document.getElementById("results");
const countEl    = document.getElementById("count");
const loadingEl  = document.getElementById("loading");

// ---- knobs (tweak as you like) ----
const DEFAULTS = {
  limit: 12,
  min_edge: 0.015,  // was 0.03
  min_trend: 0.52,  // was 0.57
  events: 12
};

// allow URL overrides, e.g. ?min_edge=0&allow_negative=1
function readOverrideNumber(name, fallback){
  const v = new URLSearchParams(location.search).get(name);
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}
function getFilters(){
  return {
    limit:     readOverrideNumber('limit',     DEFAULTS.limit),
    min_edge:  readOverrideNumber('min_edge',  DEFAULTS.min_edge),
    min_trend: readOverrideNumber('min_trend', DEFAULTS.min_trend),
    events:    readOverrideNumber('events',    DEFAULTS.events),
  };
}

function setLoading(v){ if(loadingEl) loadingEl.style.display = v ? "flex" : "none"; }
function setCount(n){ if(countEl) countEl.textContent = String(n); }
function clearResults(){ resultsEl.innerHTML = ""; setCount(0); }

async function fetchJSON(url, opts){
  const res = await fetch(url, opts);
  let data;
  try { data = await res.json(); }
  catch { throw new Error(`HTTP ${res.status}`); }
  if (!res.ok || (data && data.error)) {
    throw new Error(data?.error || `HTTP ${res.status}`);
  }
  return data;
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

function addTopCard(pick){
  const propLabel =
    pick.prop === "HITS_0_5" ? "Over 0.5 Hits" :
    pick.prop === "TB_1_5"  ? "Over 1.5 Total Bases" :
    pick.prop || "Prop";
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
          <span class="edge-badge">${pick.tag || "Fade"}</span>
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
  `;
  resultsEl.appendChild(card);
  setCount(resultsEl.children.length);
}

const leaguePath = l =>
  ({ mlb:'mlb', nfl:'nfl', ncaaf:'ncaaf', nba:'nba', nhl:'nhl', ufc:'ufc' }[(l||'mlb').toLowerCase()] || 'mlb');

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

// Tabs → switch league and refresh Top Picks
tabsEl.addEventListener("click", (e)=>{
  const btn = e.target.closest(".tab");
  if(!btn || btn.disabled) return;
  for(const b of tabsEl.querySelectorAll(".tab")) b.classList.remove("active");
  btn.classList.add("active");
  currentLeague = btn.dataset.league || "mlb";
  loadTopPicks();
});

// Button
topBtn?.addEventListener("click", loadTopPicks);

// Auto-load on first paint + one gentle retry to pick up background warmers
document.addEventListener("DOMContentLoaded", () => {
  setLoading(false);
  loadTopPicks();
  setTimeout(loadTopPicks, 3500);
});


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

