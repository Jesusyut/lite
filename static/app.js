let currentLeague = "mlb";
let selectedMlb = null; // {id, name}
let selectedNfl = null; // {id, name} when API search works; else name-only CSV mode

const tabsEl = document.getElementById("tabs");
const playerEl = document.getElementById("player");
const propEl = document.getElementById("prop");
const americanEl = document.getElementById("american");
const evalBtn = document.getElementById("evalBtn");
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
    selectedNfl = null; // NFL will use name or search endpoint on change
    return;
  }
  if(q.length < 3){ selectedMlb = null; return; }
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(async ()=>{
    try{
      const res = await fetch(`/api/mlb/search?q=${encodeURIComponent(q)}`).then(r=>r.json());
      if(res && res.length){
        selectedMlb = res[0];           // pick first match
        playerEl.value = res[0].name;   // show resolved full name
      }
    }catch(_){}
  }, 250);
});

// Optional NFL search (fires on change to save quota). If none, we stay CSV mode.
async function tryNflSearchByName(q){
  try{
    const res = await fetch(`/api/nfl/player/search?q=${encodeURIComponent(q)}`).then(r=>r.json());
    if(Array.isArray(res) && res.length){
      selectedNfl = res[0];
      playerEl.value = res[0].name;
    } else {
      selectedNfl = null; // CSV mode
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
    payload.player_name = selectedMlb.name; // needed for FanDuel odds lookup
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

// init
setPropOptions(currentLeague);
setLoading(false);
