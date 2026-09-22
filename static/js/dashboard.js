let allArticles = [];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[c]));
}

function ageLabel(iso) {
  if (!iso) return "";

  const d = new Date(iso);
  const mins = Math.max(
    0,
    Math.floor((Date.now() - d.getTime()) / 60000)
  );

  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;

  const hrs = Math.floor(mins / 60);

  if (hrs < 24) {
    return `${hrs}h ${mins % 60}m ago`;
  }

  return `${Math.floor(hrs / 24)}d ago`;
}


function render() {
  const searchEl = document.getElementById("search");
  const commodityEl = document.getElementById("commodity");
  const impactEl = document.getElementById("impact");

  const q = (searchEl?.value || "").toLowerCase().trim();
  const commodity = commodityEl?.value || "ALL";
  const impact = impactEl?.value || "ALL";

  const list = allArticles.filter(n => {
    const text = `
      ${n.title || ""}
      ${n.source || ""}
      ${n.commodity || ""}
      ${n.asset || ""}
    `.toLowerCase();

    return (
      (!q || text.includes(q)) &&
      (commodity === "ALL" || (n.commodity || n.asset) === commodity) &&
      (impact === "ALL" || n.impact === impact)
    );
  });

  const resultCount = document.getElementById("resultCount");

  if (resultCount) {
    resultCount.textContent = `${list.length} shown`;
  }

  const newsEl = document.getElementById("news");

  if (!newsEl) return;

  newsEl.innerHTML = list.map(n => {

    const safeImpact = String(n.impact || "NEUTRAL").toUpperCase();
    const cls = safeImpact.toLowerCase();

    const icon =
      safeImpact === "POSITIVE"
        ? "●"
        : safeImpact === "NEGATIVE"
          ? "●"
          : "●";

    const asset = n.asset || n.commodity || "UNCLASSIFIED";

    /*
     * IMPORTANT:
     * conclusion can legitimately be null.
     *
     * The old code did:
     *
     * n.conclusion.replace(...)
     *
     * which crashed the entire render function when conclusion was null.
     *
     * We now safely fall back to takeaway, then to an empty string.
     */
    // const rawConclusion =
    //   n.conclusion ||
    //   n.takeaway ||
    //   "";

    // const conclusion = String(rawConclusion)
    //   .replace(/^Market takeaway:\s*/i, "")
    //   .trim();

    // const takeawayHtml = conclusion
    //   ? `
    //     <div class="conclusion">
    //       <span class="conclusion-label">Market takeaway</span>
    //       <div class="conclusion-text">${esc(conclusion)}</div>
    //     </div>
    //   `
    //   : "";

    const effects = Array.isArray(n.market_effects)
      ? n.market_effects
      : [];

    const effectsHtml = effects
      .slice(0, 6)
      .map(e => {
        const effectImpact = String(
          e?.impact || "NEUTRAL"
        ).toUpperCase();

        return `
          <div class="impact-item">
            <div>
              <b>${esc(e?.asset || "")}</b>
              <span class="mini ${effectImpact.toLowerCase()}">
                ${esc(effectImpact)}
              </span>
            </div>
            <p>${esc(e?.reason || "")}</p>
          </div>
        `;
      })
      .join("");

    const url = n.url || "#";

    return `
      <article class="card">

        <div class="meta">

          <span class="badge ${cls}">
            ${icon} ${esc(safeImpact)}
          </span>

          <span class="commodity">
            ${esc(asset)}
          </span>

          <span>•</span>

          <span>
            ${esc(n.source || "")}
          </span>

          <span>•</span>

          <span>
            ${esc(
              n.time_label ||
              n.updated_label ||
              n.published_label ||
              "Time unavailable"
            )}
          </span>

          <span class="age">
            ${esc(
              ageLabel(
                n.display_time_at ||
                n.updated_at ||
                n.published_at
              )
            )}
          </span>

          <span class="confidence">
            ${esc(n.confidence ?? "")}% confidence
          </span>

        </div>

        <a
          class="title"
          href="${esc(url)}"
          target="_blank"
          rel="noopener noreferrer"
        >
          ${esc(n.title || "Untitled")}
        </a>

        

        ${
          effectsHtml
            ? `
              <div class="impact-grid">
                ${effectsHtml}
              </div>
            `
            : ""
        }

      </article>
    `;
  }).join("") || `
    <div class="empty">
      No matching headlines. Try another commodity or search term.
    </div>
  `;
}


function updateCommodityFilter() {
  const select = document.getElementById("commodity");

  if (!select) return;

  const current = select.value;

  const values = [
    ...new Set(
      allArticles
        .map(x => x.commodity || x.asset)
        .filter(Boolean)
    )
  ].sort();

  select.innerHTML =
    `<option value="ALL">All commodities</option>` +
    values
      .map(x =>
        `<option value="${esc(x)}">${esc(x)}</option>`
      )
      .join("");

  select.value = values.includes(current)
    ? current
    : "ALL";
}


function renderSources(sources) {
  const sourcesEl = document.getElementById("sources");

  if (!sourcesEl) return;

  sourcesEl.innerHTML = Object.entries(sources || {})
    .map(([name, s]) => {

      const ok = Boolean(s?.ok);

      return `
        <div class="source-row">

          <span>
            ${esc(name)}
          </span>

          <span class="${ok ? "ok" : "bad"}">
            ${
              ok
                ? "● Online"
                : "● " + esc(s?.message || "Unavailable")
            }
            · ${esc(s?.articles ?? 0)} items
          </span>

        </div>
      `;
    })
    .join("");
}


async function loadNews() {
  const btn = document.getElementById("refreshBtn");

  if (btn) {
    btn.disabled = true;
    btn.textContent = "Refreshing…";
  }

  try {

    const res = await fetch(
      "/api/news?ts=" + Date.now(),
      {
        cache: "no-store"
      }
    );

    if (!res.ok) {
      throw new Error(
        `API returned HTTP ${res.status}`
      );
    }

    const data = await res.json();

    /*
     * API format:
     *
     * {
     *   articles: [...],
     *   count: 247,
     *   sources: {...}
     * }
     */

    if (!data || !Array.isArray(data.articles)) {
      throw new Error(
        "API response does not contain an articles array"
      );
    }

    allArticles = data.articles;

    updateCommodityFilter();
    render();
    renderSources(data.sources);

    const articleCount =
      document.getElementById("articleCount");

    if (articleCount) {
      articleCount.textContent =
        data.count ?? allArticles.length;
    }


    const sourceCount =
      document.getElementById("sourceCount");

    if (sourceCount) {
      sourceCount.textContent =
        `${data.sources_ok ?? 0}/${data.sources_total ?? 0}`;
    }


    const latestAge =
      document.getElementById("latestAge");

    if (latestAge) {

      latestAge.textContent =
        data.latest_age_minutes == null
          ? "—"
          : data.latest_age_minutes < 60
            ? `${data.latest_age_minutes}m`
            : `${Math.floor(
                data.latest_age_minutes / 60
              )}h`;
    }


    const updated =
      document.getElementById("updated");

    if (updated) {

      updated.textContent =
        data.updated_at
          ? `Updated ${new Date(
              data.updated_at
            ).toLocaleTimeString()}`
          : "Waiting…";
    }

  } catch (e) {

    console.error(
      "Failed to load/render news:",
      e
    );

    const updated =
      document.getElementById("updated");

    if (updated) {
      updated.textContent =
        "Connection error — retrying";
    }

  } finally {

    if (btn) {
      btn.disabled = false;
      btn.textContent = "↻ Refresh now";
    }
  }
}


/* Search */
const searchEl =
  document.getElementById("search");

if (searchEl) {
  searchEl.addEventListener(
    "input",
    render
  );
}


/* Commodity filter */
const commodityEl =
  document.getElementById("commodity");

if (commodityEl) {
  commodityEl.addEventListener(
    "change",
    render
  );
}


/* Impact filter */
const impactEl =
  document.getElementById("impact");

if (impactEl) {
  impactEl.addEventListener(
    "change",
    render
  );
}


/* Manual refresh */
const refreshBtn =
  document.getElementById("refreshBtn");

if (refreshBtn) {
  refreshBtn.addEventListener(
    "click",
    loadNews
  );
}


/* Initial load */
loadNews();


/*
 * Automatic refresh.
 *
 * refreshSeconds comes from the page/template.
 * Fall back to 60 seconds if it isn't defined.
 */
const refreshInterval =
  typeof refreshSeconds !== "undefined"
    ? refreshSeconds
    : 60;

setInterval(
  loadNews,
  refreshInterval * 1000
);