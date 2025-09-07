const leagueEl = document.getElementById("league");
const propEl = document.getElementById("prop");
const playerEl = document.getElementById("player");
const americanEl = document.getElementById("american");
const resultEl = document.getElementById("result");
const evalBtn = document.getElementById("eval");

let selectedMlb = null;
playerEl.addEventListener("input", async (e)=>{
  if(leagueEl.value!=="mlb"){ selectedMlb=null; return; }
  const q = playerEl.value.trim();
  if(q.length<3){ return; }
  const res = await fetch(`/api/mlb/search?q=${encodeURIComponent(q)}`).then(r=>r.json());
  if(res.length){
    selectedMlb = res[0];
    playerEl.value = `${selectedMlb.name}`;
  }
});

evalBtn.addEventListener("click", async ()=>{
  const league = leagueEl.value, prop = propEl.value;
  const american = americanEl.value ? Number(americanEl.value) : null;
  let body = { league, prop, american };

  if(league==="mlb"){
    if(!selectedMlb){ resultEl.textContent="Pick an MLB player (type to search)"; return; }
    body.player_id = selectedMlb.id;
  }else{
    if(!playerEl.value.trim()){ resultEl.textContent="Enter NFL player name (matches CSV)"; return; }
    body.player_name = playerEl.value.trim();
  }
  resultEl.textContent = "Evaluating...";
  const res = await fetch("/api/evaluate", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(body)
  }).then(r=>r.json());

  if(res.error){ resultEl.textContent = res.error; return; }
  const be = res.break_even_prob!=null ? `Break-even: ${(res.break_even_prob*100).toFixed(1)}%` : "No price given";
  resultEl.innerHTML = `
    <div class="card">
      <div><b>Trend hit prob:</b> ${(res.p_trend*100).toFixed(1)}%</div>
      <div><b>${be}</b></div>
      <div><b>Tag:</b> ${res.tag}</div>
    </div>`;
});
