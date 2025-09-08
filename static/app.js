let currentLeague = "mlb";
let selectedMlb = null; // {id, name}
let selectedNfl = null; // {id, name}

const tabsEl = document.getElementById("tabs");
const playerEl = document.getElementById("player");
const propEl = document.getElementById("prop");
const americanEl = document.getElementById("american");
const evalBtn = document.getElementById("evalBtn");
const topBtn = document.getElementById("topBtn");
const resultsEl = document.getElementById("results");
const countEl = document.getElementById("count");
const loadingEl = document.getElementById("loading");

function setLoading(v){ loadingEl.style.display = v ? "flex" : "none"; }
function setCount(n){ countEl.textContent = String(n); }
function clearResults(){ resultsEl.innerHTML = ""; setCount(0); }

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
  const step = w / n;
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
  const subtitleParts = [
    `Line ${Number(pick.line).toFixed(1)}`,
    `Trend ${(pick.p_trend*100).toFixed(1)}%`,
    `Break-even ${(pick.break_even_prob*100).toFixed(1)}%`
  ];
  const subtitle = subtitleParts.join(" • ");
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
    // force MLB tab
    for(const b of tabsEl.querySelectorAll(".tab")) {
      if (b.dataset.league === "mlb") b.classList.add("active"); else b.classList.remove("active");
    }
    currentLeague = "mlb";
    setPropOptions(currentLeague);

    selectedMlb = { id: pick.player_id, name: pick.player_name };
    playerEl.value = pick.player_name;
    propEl.value = pick.prop;
    americanEl.value = pick.american ?? "";

    // Optionally auto-run evaluate:
    // evalBtn.click();
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

evalBtn.addEventListener("click", async ()=>{
  clearResults();

  const prop = propEl.value;
  const americanRaw = americanEl.value.trim();
  const american = americanRaw ? Number(americanRaw) : null;
  let payload = { league: currentLeague, prop, american };

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
    if(selectedNfl){ payload.player_id = selectedNfl.id; title = `${selectedNfl.name}`; }
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
    const res = await fetch("/api/evaluate", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    }).then(r=>r.json());

    if(res.error){
      addResultCard({title:"Error", subtitle:String(res.error), pTrend:0, breakEven:null, tag:"Fade"});
    }else{
      const parts = [];
      if (res.used_line != null) parts.push(`Line ${Number(res.used_line).toFixed(1)}`);
      parts.push(`Trend ${(res.p_trend*100).toFixed(1)}%`);
      if (res.break_even_prob != null) parts.push(`Break-even ${(res.break_even_prob*100).toFixed(1)}%`);
      const subtitle = parts.join(" • ");

      addResultCard({
        title,
        subtitle,
        pTrend: res.p_trend || 0,
        breakEven: res.break_even_prob,
        tag: res.tag || "Fade"
      });
    }
  }catch(_){
    addResultCard({title:"Error", subtitle:"Request failed", pTrend:0, breakEven:null, tag:"Fade"});
  }finally{
    setLoading(false);
  }
});

// Top Picks (MLB)
async function loadTopPicks(){
  clearResults();
  setLoading(true);
  try{
    const r = await fetch("/api/top/mlb?limit=12");
    if(!r.ok){
      const msg = `Top picks request failed (${r.status})`;
      addResultCard({title:"Error", subtitle:msg, pTrend:0, breakEven:null, tag:"Fade"});
      return;
    }
    const list = await r.json();
    if(Array.isArray(list) && list.length){
      for(const p of list) addTopCard(p);
    } else {
      addResultCard({title:"No picks", subtitle:"No FanDuel candidates within ±250 (or odds feed empty).", pTrend:0, breakEven:null, tag:"Fade"});
    }
  }catch(e){
    addResultCard({title:"Error", subtitle:"Could not load top picks", pTrend:0, breakEven:null, tag:"Fade"});
  }finally{
    setLoading(false);
  }
}

