let allArticles = [];

function esc(s){
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[c]));
}

function ageLabel(iso){
  if(!iso) return "";
  const d = new Date(iso), mins = Math.max(0, Math.floor((Date.now()-d.getTime())/60000));
  if(mins < 1) return "just now";
  if(mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins/60);
  if(hrs < 24) return `${hrs}h ${mins%60}m ago`;
  return `${Math.floor(hrs/24)}d ago`;
}

function render(){
  const q = document.getElementById("search").value.toLowerCase().trim();
  const commodity = document.getElementById("commodity").value;
  const impact = document.getElementById("impact").value;

  const list = allArticles.filter(n => {
    const text = `${n.title} ${n.source} ${n.commodity}`.toLowerCase();
    return (!q || text.includes(q))
      && (commodity === "ALL" || n.commodity === commodity)
      && (impact === "ALL" || n.impact === impact);
  });

  document.getElementById("resultCount").textContent = `${list.length} shown`;

  document.getElementById("news").innerHTML = list.map(n => {
    const cls = n.impact.toLowerCase();
    const icon = n.impact === "POSITIVE" ? "●" : n.impact === "NEGATIVE" ? "●" : "●";
    return `<article class="card">
      <div class="meta">
        <span class="badge ${cls}">${icon} ${esc(n.impact)}</span>
        <span class="commodity">${esc(n.commodity)}</span>
        <span>•</span><span>${esc(n.source)}</span>
        <span>•</span><span>${esc(n.time_label || n.published_label || "Time unavailable")}</span>
        <span class="age">${ageLabel(n.display_time_at || n.published_at)}</span>
        <span class="confidence">${n.confidence}% confidence</span>
      </div>
      <a class="title" href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>
      <div class="conclusion"><span class="conclusion-label">Market takeaway</span><div class="conclusion-text">${esc(n.conclusion.replace(/^Market takeaway:\s*/i, ""))}</div></div>
      <div class="impact-grid">
        ${(n.market_effects || []).slice(0, 6).map(e =>
          `<div class="impact-item">
            <div><b>${esc(e.asset)}</b><span class="mini ${e.impact.toLowerCase()}">${esc(e.impact)}</span></div>
            <p>${esc(e.reason)}</p>
          </div>`
        ).join("")}
      </div>
    </article>`;
  }).join("") || `<div class="empty">No matching headlines. Try another commodity or search term.</div>`;
}

function updateCommodityFilter(){
  const select = document.getElementById("commodity");
  const current = select.value;
  const values = [...new Set(allArticles.map(x => x.commodity))].sort();
  select.innerHTML = `<option value="ALL">All commodities</option>` +
    values.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
  select.value = values.includes(current) ? current : "ALL";
}

function renderSources(sources){
  document.getElementById("sources").innerHTML = Object.entries(sources || {}).map(([name, s]) =>
    `<div class="source-row">
      <span>${esc(name)}</span>
      <span class="${s.ok ? "ok":"bad"}">${s.ok ? "● Online":"● "+esc(s.message)} · ${s.articles} items</span>
    </div>`
  ).join("");
}

async function loadNews(){
  const btn = document.getElementById("refreshBtn");
  btn.disabled = true;
  btn.textContent = "Refreshing…";
  try{
    const res = await fetch("/api/news?ts="+Date.now(), {cache:"no-store"});
    const data = await res.json();
    allArticles = data.articles || [];
    updateCommodityFilter();
    render();
    renderSources(data.sources);

    document.getElementById("articleCount").textContent = data.count ?? "0";
    document.getElementById("sourceCount").textContent = `${data.sources_ok ?? 0}/${data.sources_total ?? 0}`;
    document.getElementById("latestAge").textContent =
      data.latest_age_minutes == null ? "—" :
      data.latest_age_minutes < 60 ? `${data.latest_age_minutes}m` :
      `${Math.floor(data.latest_age_minutes/60)}h`;

    document.getElementById("updated").textContent =
      data.updated_at ? `Updated ${new Date(data.updated_at).toLocaleTimeString()}` : "Waiting…";
  }catch(e){
    document.getElementById("updated").textContent = "Connection error — retrying";
  }finally{
    btn.disabled = false;
    btn.textContent = "↻ Refresh now";
  }
}

document.getElementById("search").addEventListener("input", render);
document.getElementById("commodity").addEventListener("change", render);
document.getElementById("impact").addEventListener("change", render);
document.getElementById("refreshBtn").addEventListener("click", loadNews);

loadNews();
setInterval(loadNews, refreshSeconds * 1000);
