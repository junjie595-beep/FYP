const searchInput = document.getElementById("searchInput");
const searchBtn = document.getElementById("searchBtn");
const searchStatus = document.getElementById("searchStatus");
const results = document.getElementById("results");
const playlistEl = document.getElementById("playlist");
const playlistCount = document.getElementById("playlistCount");
const playPlaylistBtn = document.getElementById("playPlaylistBtn");
const recommendBtn = document.getElementById("recommendBtn");
const clearBtn = document.getElementById("clearBtn");
const recommendationEl = document.getElementById("recommendation");
const apiOutput = document.getElementById("apiOutput");
const strategyEl = document.getElementById("strategy");
const audioPlayer = document.getElementById("audioPlayer");
const nowTitle = document.getElementById("nowTitle");
const nowArtist = document.getElementById("nowArtist");
const recommendationMode = document.getElementById("recommendationMode");
const modeDescription = document.getElementById("modeDescription");

const MODE_DESCRIPTIONS = {
  familiar: "Prioritises relevant songs and artists already represented in your playlist.",
  balanced: "Balances relevant matches with a varied selection of artists.",
  discover: "Prioritises new artists and allows only one recommendation per artist."
};

let playlist = JSON.parse(localStorage.getItem("nexttrack_playlist") || "[]");
let history = JSON.parse(localStorage.getItem("nexttrack_history") || "[]");
let currentPlaylistIndex = -1;

function updateRecommendationMode() {
  const selectedMode = recommendationMode.value;
  modeDescription.textContent = MODE_DESCRIPTIONS[selectedMode];
  localStorage.setItem("nexttrack_recommendation_mode", selectedMode);
}

function saveState() {
  localStorage.setItem("nexttrack_playlist", JSON.stringify(playlist));
  localStorage.setItem("nexttrack_history", JSON.stringify(history));
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function trackCard(track, actions = []) {
  const cover = track.cover || "";
  const actionButtons = actions.map(action => {
    return `<button class="${action.className || ""}" data-action="${action.name}" data-id="${escapeHtml(track.id)}">${action.label}</button>`;
  }).join("");

  const genres = (track.genres || []).filter(Boolean);
  const genreHtml = genres.length
    ? `<div class="genre-row">${genres.map(genre => `<span class="genre-pill">${escapeHtml(genre)}</span>`).join("")}</div>`
    : `<div class="genre-row"><span class="genre-pill muted">No genre found</span></div>`;

  return `
    <div class="track-card" data-track-id="${escapeHtml(track.id)}">
      <img src="${escapeHtml(cover)}" alt="Album cover" onerror="this.style.visibility='hidden'">
      <div>
        <div class="track-title">${escapeHtml(track.title)}</div>
        <div class="track-meta">${escapeHtml(track.artist)}${track.album ? " • " + escapeHtml(track.album) : ""}</div>
        ${genreHtml}
        <div class="track-actions">${actionButtons}</div>
      </div>
    </div>
  `;
}

function renderPlaylist() {
  playlistCount.textContent = `${playlist.length} song${playlist.length === 1 ? "" : "s"}`;
  if (playlist.length === 0) {
    playlistEl.innerHTML = `<p class="hint">No songs yet. Add tracks from the search results.</p>`;
    return;
  }

  playlistEl.innerHTML = playlist.map(track => trackCard(track, [
    { name: "play-playlist-track", label: "Play" },
    { name: "remove", label: "Remove", className: "danger" }
  ])).join("");
}

function setNowPlaying(track) {
  nowTitle.textContent = track.title || "Unknown title";
  nowArtist.textContent = track.artist || "Unknown artist";
}

function playTrack(track) {
  if (!track || !track.preview_url) {
    alert("This track does not have a playable preview URL.");
    return;
  }
  audioPlayer.src = track.preview_url;
  audioPlayer.play();
  setNowPlaying(track);

  if (!history.includes(String(track.id))) {
    history.push(String(track.id));
    history = history.slice(-50);
    saveState();
  }
}

async function playPlaylistFrom(index = 0) {
  if (playlist.length === 0) {
    alert("Add songs to your playlist first.");
    return;
  }

  if (index < 0 || index >= playlist.length) return;

  currentPlaylistIndex = index;
  const savedTrack = playlist[index];

  try {
    const response = await fetch(
      `/api/track/${encodeURIComponent(savedTrack.id)}`
    );
    const data = await response.json();

    if (!response.ok || !data.track) {
      throw new Error(data.error || "Could not refresh this track.");
    }

    playlist[index] = { ...savedTrack, ...data.track };
    saveState();
    playTrack(playlist[index]);
  } catch (error) {
    alert(`Could not play this song: ${error.message}`);
  }
}

audioPlayer.addEventListener("ended", () => {
  if (
    currentPlaylistIndex >= 0 &&
    currentPlaylistIndex < playlist.length - 1
  ) {
    playPlaylistFrom(currentPlaylistIndex + 1);
  }
});

async function searchMusic() {
  const q = searchInput.value.trim();
  if (!q) {
    searchStatus.textContent = "Enter a search keyword first.";
    return;
  }

  searchStatus.textContent = "Searching...";
  results.innerHTML = "";

  try {
    const response = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=15`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Search failed");
    }

    const tracks = data.tracks || [];
    searchStatus.textContent = `${tracks.length} result${tracks.length === 1 ? "" : "s"} found.`;

    if (tracks.length === 0) {
      results.innerHTML = `<p class="hint">No playable previews found. Try another keyword.</p>`;
      return;
    }

    results.innerHTML = tracks.map(track => trackCard(track, [
      { name: "play-result", label: "Play preview" },
      { name: "add", label: "Add to playlist", className: "primary" }
    ])).join("");

    window.latestSearchResults = tracks;
  } catch (error) {
    searchStatus.textContent = error.message;
  }
}

function findTrackById(id) {
  const pools = [window.latestSearchResults || [], playlist, window.latestRecommendations || []];
  for (const pool of pools) {
    const found = pool.find(track => String(track.id) === String(id));
    if (found) return found;
  }
  return null;
}

function addToPlaylist(track) {
  if (!track) return;
  if (playlist.some(item => String(item.id) === String(track.id))) {
    alert("This song is already in your playlist.");
    return;
  }
  playlist.push(track);
  saveState();
  renderPlaylist();
}

function removeFromPlaylist(id) {
  playlist = playlist.filter(track => String(track.id) !== String(id));
  saveState();
  renderPlaylist();
}

function recommendationDetails(track) {
  const hasMatchScore = Number.isFinite(Number(track.match_score));
  const matchScore = hasMatchScore ? Math.max(0, Math.min(100, Number(track.match_score))) : null;
  const rawScore = Number.isFinite(Number(track.recommendation_score))
    ? Number(track.recommendation_score)
    : null;

  const scoreHtml = matchScore === null
    ? ""
    : `
      <div class="match-summary" aria-label="${matchScore}% recommendation match">
        <span class="match-score">${matchScore}% match</span>
        ${rawScore === null ? "" : `<span class="raw-score">Relevance score: ${rawScore}</span>`}
      </div>
      <div class="match-bar" aria-hidden="true">
        <span style="width: ${matchScore}%"></span>
      </div>
    `;

  const reasons = Array.isArray(track.recommendation_reasons)
    ? track.recommendation_reasons.filter(Boolean)
    : [track.recommendation_reason || "Recommended from your playlist."];

  const reasonHtml = `
    <div class="recommendation-explanation">
      <p class="explanation-heading">Why this was recommended</p>
      <ul>
        ${reasons.map(reason => `<li>${escapeHtml(reason)}</li>`).join("")}
      </ul>
    </div>
  `;

  const matchedTerms = ((track.score_breakdown || {}).matched_terms || [])
    .filter(item => item && item.term);
  const termsHtml = matchedTerms.length
    ? `
      <div class="matched-terms">
        ${matchedTerms.map(item => `
          <span class="matched-term" title="Scoring weight: ${escapeHtml(item.weight)}">
            ${escapeHtml(item.term)} +${escapeHtml(item.weight)}
          </span>
        `).join("")}
      </div>
    `
    : "";

  return `${scoreHtml}${reasonHtml}${termsHtml}`;
}

async function recommendNext() {
  if (playlist.length === 0) {
    alert("Add at least one song to your playlist first.");
    return;
  }

  recommendationEl.classList.remove("recommendation-empty");
  recommendationEl.innerHTML = `<p class="hint">Finding recommendation...</p>`;
  strategyEl.textContent = "Loading";

  try {
    const response = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        playlist,
        history,
        query: searchInput.value.trim(),
        count: 6,
        mode: recommendationMode.value
      })
    });

    const data = await response.json();
    apiOutput.textContent = JSON.stringify(data, null, 2);

    if (!response.ok) {
      throw new Error(data.error || "Recommendation failed");
    }

    const tracks = data.recommendations || (data.recommendation ? [data.recommendation] : []);
    window.latestRecommendations = tracks;
    const selectedModeLabel = data.based_on?.recommendation_mode_label || "Balanced";
    strategyEl.textContent = `${selectedModeLabel}: ${tracks.length} recommendation${tracks.length === 1 ? "" : "s"}`;

    recommendationEl.innerHTML = tracks.map((track, index) => {
      const title = index === 0 ? `<p class="best-match">Best match</p>` : "";
      return `<div class="recommendation-item">${title}${trackCard(track, [
        { name: "play-recommendation", label: "Play preview" },
        { name: "add", label: "Add to playlist", className: "primary" }
      ])}${recommendationDetails(track)}</div>`;
    }).join("");
  } catch (error) {
    recommendationEl.classList.add("recommendation-empty");
    recommendationEl.innerHTML = `<p class="hint">${escapeHtml(error.message)}</p>`;
    strategyEl.textContent = "Error";
  }
}

searchBtn.addEventListener("click", searchMusic);
searchInput.addEventListener("keydown", event => {
  if (event.key === "Enter") searchMusic();
});

results.addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button) return;
  const track = findTrackById(button.dataset.id);
  if (button.dataset.action === "play-result") playTrack(track);
  if (button.dataset.action === "add") addToPlaylist(track);
});

playlistEl.addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button) return;
  const id = button.dataset.id;
  const index = playlist.findIndex(track => String(track.id) === String(id));
  if (button.dataset.action === "play-playlist-track") playPlaylistFrom(index);
  if (button.dataset.action === "remove") removeFromPlaylist(id);
});

recommendationEl.addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button) return;
  const track = findTrackById(button.dataset.id);
  if (button.dataset.action === "play-recommendation") playTrack(track);
  if (button.dataset.action === "add") addToPlaylist(track);
});

playPlaylistBtn.addEventListener("click", () => playPlaylistFrom(0));
recommendBtn.addEventListener("click", recommendNext);
recommendationMode.addEventListener("change", updateRecommendationMode);
clearBtn.addEventListener("click", () => {
  playlist = [];
  currentPlaylistIndex = -1;
  saveState();
  renderPlaylist();
});

const savedMode = localStorage.getItem("nexttrack_recommendation_mode");
if (savedMode && MODE_DESCRIPTIONS[savedMode]) {
  recommendationMode.value = savedMode;
}
updateRecommendationMode();
renderPlaylist();
