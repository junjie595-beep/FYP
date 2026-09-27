import os
import time
from collections import Counter
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "").strip()
APP_NAME = os.getenv("APP_NAME", "NextTrack")
APP_VERSION = os.getenv("APP_VERSION", "1.0")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "example@example.com")

DEEZER_BASE = "https://api.deezer.com"
LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"
MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"

REQUEST_TIMEOUT = 10

session = requests.Session()
session.headers.update({
    "User-Agent": f"{APP_NAME}/{APP_VERSION} ({CONTACT_EMAIL})"
})

# Simple in-memory cache to reduce repeated external API calls during testing.
CACHE = {}
CACHE_TTL = 60 * 10

# Common words that do not provide useful evidence for music similarity.
STOP_WORDS = {
    "and", "the", "for", "with", "from", "this", "that", "version",
    "remaster", "remastered", "feat", "featuring"
}

RECOMMENDATION_MODES = {
    "familiar": {
        "label": "Familiar",
        "artist_bonus": 4,
        "new_artist_bonus": 0,
        "max_per_artist": 3,
    },
    "balanced": {
        "label": "Balanced",
        "artist_bonus": 2,
        "new_artist_bonus": 0,
        "max_per_artist": 2,
    },
    "discover": {
        "label": "Discover",
        "artist_bonus": 0,
        "new_artist_bonus": 2,
        "max_per_artist": 1,
    },
}


def recommendation_mode(value):
    mode = str(value or "balanced").strip().lower()
    if mode not in RECOMMENDATION_MODES:
        mode = "balanced"
    return mode, RECOMMENDATION_MODES[mode]


def cached_get(url, params=None):
    params_tuple = tuple(sorted((params or {}).items()))
    key = (url, params_tuple)
    now = time.time()
    if key in CACHE:
        saved_time, data = CACHE[key]
        if now - saved_time < CACHE_TTL:
            return data

    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    CACHE[key] = (now, data)
    return data


def normalise_deezer_track(track):
    artist = track.get("artist") or {}
    album = track.get("album") or {}
    return {
        "id": str(track.get("id")),
        "title": track.get("title") or "Unknown title",
        "artist": artist.get("name") or "Unknown artist",
        "artist_id": str(artist.get("id")) if artist.get("id") else None,
        "album_id": str(album.get("id")) if album.get("id") else None,
        "album": album.get("title") or "",
        "cover": album.get("cover_medium") or album.get("cover") or "",
        "duration": track.get("duration"),
        "preview_url": track.get("preview") or "",
        "deezer_link": track.get("link") or "",
        "genres": track.get("genres") or [],
        "source": "deezer"
    }


def deezer_search(query, limit=12):
    query = (query or "").strip()
    if not query:
        query = "pop"

    data = cached_get(f"{DEEZER_BASE}/search", {
        "q": query,
        "limit": max(1, min(int(limit), 25))
    })
    return [normalise_deezer_track(track) for track in data.get("data", []) if track.get("preview")]


def deezer_track(track_id):
    data = cached_get(f"{DEEZER_BASE}/track/{track_id}")
    if "error" in data:
        return None
    return normalise_deezer_track(data)


def clean_tag(value):
    value = (value or "").strip()
    if not value:
        return ""
    blocked = {"seen live", "favorites", "favourite", "favorite", "spotify", "deezer"}
    lowered = value.lower()
    if lowered in blocked or len(lowered) > 28:
        return ""
    return value.title()


def deezer_album_genres(album_id, limit=4):
    if not album_id:
        return []
    try:
        data = cached_get(f"{DEEZER_BASE}/album/{album_id}")
    except Exception:
        return []

    genres = []
    for item in (data.get("genres") or {}).get("data", []):
        name = clean_tag(item.get("name"))
        if name and name not in genres:
            genres.append(name)
        if len(genres) >= limit:
            break
    return genres


def lastfm_track_tags(title, artist, limit=4):
    if not LASTFM_API_KEY or not title or not artist:
        return []

    try:
        data = cached_get(LASTFM_BASE, {
            "method": "track.getInfo",
            "track": title,
            "artist": artist,
            "api_key": LASTFM_API_KEY,
            "format": "json",
            "autocorrect": 1
        })
    except Exception:
        return []

    tags = []
    for item in ((data.get("track") or {}).get("toptags") or {}).get("tag", []):
        name = clean_tag(item.get("name"))
        if name and name not in tags:
            tags.append(name)
        if len(tags) >= limit:
            break
    return tags


def fallback_genres_from_text(*values, limit=4):
    known = [
        "pop", "rock", "jazz", "hip hop", "rap", "r&b", "soul", "classical",
        "electronic", "dance", "house", "techno", "metal", "indie", "folk",
        "country", "blues", "reggae", "latin", "kpop", "lofi", "ambient",
        "acoustic", "piano", "chill", "happy", "sad", "energetic"
    ]
    text = " ".join(values).lower()
    found = []
    for tag in known:
        if tag in text:
            found.append(tag.title())
        if len(found) >= limit:
            break
    return found


def enrich_track_genres(track, fallback_text=""):
    """Attach genre/tag labels for display and scoring.

    Deezer search results do not always include genre names directly. This tries
    Deezer album genres first, then Last.fm tags, then a small keyword fallback.
    """
    if not track:
        return track

    genres = []
    for name in track.get("genres") or []:
        cleaned = clean_tag(name)
        if cleaned and cleaned not in genres:
            genres.append(cleaned)

    for name in deezer_album_genres(track.get("album_id")):
        if name not in genres:
            genres.append(name)

    for name in lastfm_track_tags(track.get("title"), track.get("artist")):
        if name not in genres:
            genres.append(name)

    if not genres:
        genres = fallback_genres_from_text(
            fallback_text, track.get("title", ""), track.get("artist", ""), track.get("album", "")
        )

    track["genres"] = genres[:5]
    return track


def musicbrainz_match(title, artist):
    """Return MusicBrainz recording metadata for explainability, not playback."""
    if not title or not artist:
        return None

    query = f'recording:"{title}" AND artist:"{artist}"'
    try:
        data = cached_get(f"{MUSICBRAINZ_BASE}/recording", {
            "query": query,
            "fmt": "json",
            "limit": 1
        })
    except Exception:
        return None

    recordings = data.get("recordings", [])
    if not recordings:
        return None

    recording = recordings[0]
    artist_credit = recording.get("artist-credit", [])
    artist_name = ""
    artist_mbid = ""
    if artist_credit and isinstance(artist_credit[0], dict):
        artist_obj = artist_credit[0].get("artist", {})
        artist_name = artist_obj.get("name", "")
        artist_mbid = artist_obj.get("id", "")

    return {
        "recording_mbid": recording.get("id", ""),
        "title": recording.get("title", title),
        "artist": artist_name or artist,
        "artist_mbid": artist_mbid,
        "score": recording.get("score")
    }


def lastfm_similar_tracks(title, artist, limit=10):
    if not LASTFM_API_KEY or not title or not artist:
        return []

    try:
        data = cached_get(LASTFM_BASE, {
            "method": "track.getSimilar",
            "track": title,
            "artist": artist,
            "api_key": LASTFM_API_KEY,
            "format": "json",
            "limit": limit,
            "autocorrect": 1
        })
    except Exception:
        return []

    similar = data.get("similartracks", {}).get("track", [])
    results = []
    for item in similar:
        results.append({
            "title": item.get("name", ""),
            "artist": (item.get("artist") or {}).get("name", ""),
            "match": item.get("match", "")
        })
    return results


def playlist_terms(playlist):
    terms = []
    for track in playlist:
        title = track.get("title", "")
        artist = track.get("artist", "")
        album = track.get("album", "")
        if artist:
            terms.append(artist)
        if album:
            terms.append(album)
        for genre in track.get("genres") or []:
            terms.append(genre)
        # The full artist name is already stored above and receives a separate
        # artist-match bonus. Only split the title to avoid double-counting
        # individual artist-name words.
        for word in title.replace("-", " ").split():
            cleaned = "".join(ch for ch in word.lower() if ch.isalnum())
            if len(cleaned) > 2 and cleaned not in STOP_WORDS:
                terms.append(cleaned)
    return terms


def score_candidate(
    candidate,
    playlist,
    preferred_terms,
    artist_bonus=2,
    new_artist_bonus=0,
):
    """Return the candidate's numeric relevance score.

    This function still returns an integer so that existing code and tests remain
    compatible. Detailed evidence is produced by score_candidate_details().
    """
    return score_candidate_details(
        candidate,
        playlist,
        preferred_terms,
        artist_bonus=artist_bonus,
        new_artist_bonus=new_artist_bonus,
    )["score"]


def score_candidate_details(
    candidate,
    playlist,
    preferred_terms,
    artist_bonus=2,
    new_artist_bonus=0,
):
    """Score a track and explain which playlist evidence affected the score."""
    candidate_text = (
        f"{candidate.get('title', '')} {candidate.get('artist', '')} "
        f"{candidate.get('album', '')} {' '.join(candidate.get('genres', []))}"
    ).lower()

    matched_terms = []
    term_score = 0
    for term, weight in preferred_terms.items():
        if term and term.lower() in candidate_text:
            matched_terms.append({"term": term.title(), "weight": weight})
            term_score += weight

    candidate_artist = candidate.get("artist", "").strip().lower()
    playlist_artists = {
        track.get("artist", "").strip().lower()
        for track in playlist
        if track.get("artist")
    }
    artist_match = bool(candidate_artist and candidate_artist in playlist_artists)
    new_artist_match = bool(candidate_artist and candidate_artist not in playlist_artists)
    artist_score = artist_bonus if artist_match else 0
    discovery_score = new_artist_bonus if new_artist_match else 0
    total_score = term_score + artist_score + discovery_score

    possible_score = sum(preferred_terms.values()) + max(
        artist_bonus,
        new_artist_bonus,
    )
    match_percentage = round((total_score / possible_score) * 100) if possible_score else 0
    match_percentage = max(0, min(match_percentage, 100))

    reasons = []
    if matched_terms:
        names = ", ".join(item["term"] for item in matched_terms[:3])
        reasons.append(f"Matched playlist terms: {names}")
    if artist_match and artist_bonus:
        reasons.append("Artist already appears in your playlist")
    if new_artist_match and new_artist_bonus:
        reasons.append("Artist is new to your playlist")
    if candidate.get("lastfm_match"):
        reasons.append("Last.fm identified it as similar to your latest track")
    if not reasons:
        reasons.append("Discovered from the combined playlist search terms")

    return {
        "score": total_score,
        "match_percentage": match_percentage,
        "matched_terms": matched_terms,
        "artist_match": artist_match,
        "new_artist_match": new_artist_match,
        "artist_bonus": artist_score,
        "new_artist_bonus": discovery_score,
        "reasons": reasons
    }


def diversity_rank(candidates, count=5, max_per_artist=2):
    """Select relevant tracks while limiting repeated artists.

    A second pass fills any remaining spaces when the external APIs return too
    few different artists, so the endpoint can still return the requested count.
    """
    requested_count = max(1, int(count))
    selected = []
    selected_ids = set()
    artist_counts = Counter()

    for track in candidates:
        artist_key = track.get("artist", "Unknown artist").strip().lower()
        if artist_counts[artist_key] >= max_per_artist:
            continue
        selected.append(track)
        selected_ids.add(str(track.get("id")))
        artist_counts[artist_key] += 1
        if len(selected) >= requested_count:
            return selected

    for track in candidates:
        track_id = str(track.get("id"))

        artist_key = (
            track
            .get("artist", "Unknown artist")
            .strip()
            .lower()
        )

        if track_id in selected_ids:
            continue

        if artist_counts[artist_key] >= max_per_artist:
            continue

        selected.append(track)
        selected_ids.add(track_id)
        artist_counts[artist_key] += 1

        if len(selected) >= requested_count:
            break

    return selected


def recommend_from_playlist(
    playlist,
    history=None,
    search_query="",
    limit=12,
    count=5,
    mode="balanced",
):
    history = {str(item) for item in (history or [])}
    playlist = playlist or []
    mode_key, mode_config = recommendation_mode(mode)

    playlist_artist_counts = Counter(
        track.get("artist", "").strip()
        for track in playlist
        if track.get("artist", "").strip()
    )
    familiar_artists = [
        artist
        for artist, _frequency in playlist_artist_counts.most_common(3)
    ]
    playlist_artist_keys = {
        artist.lower()
        for artist in playlist_artist_counts
    }

    # Prefer Last.fm similar tracks from the latest playlist song.
    seed_track = playlist[-1] if playlist else None
    candidates = []
    explanation = {
        "strategy": "fallback_deezer_search",
        "seed_track": seed_track,
        "used_lastfm": False,
        "used_musicbrainz": False,
        "search_terms": [],
        "recommendation_mode": mode_key,
        "recommendation_mode_label": mode_config["label"],
        "maximum_tracks_per_artist": mode_config["max_per_artist"],
        "artist_bonus": mode_config["artist_bonus"],
        "new_artist_bonus": mode_config["new_artist_bonus"],
        "familiar_artists": familiar_artists,
        "excluded_playlist_artists": 0,
    }

    if seed_track:
        mb = musicbrainz_match(seed_track.get("title"), seed_track.get("artist"))
        if mb:
            explanation["musicbrainz_match"] = mb
            explanation["used_musicbrainz"] = True

        similar = lastfm_similar_tracks(seed_track.get("title"), seed_track.get("artist"), limit=8)
        if similar:
            explanation["strategy"] = "lastfm_similar_then_deezer_preview_lookup"
            explanation["used_lastfm"] = True
            for item in similar:
                q = f'artist:"{item["artist"]}" track:"{item["title"]}"'
                found = deezer_search(q, limit=3)
                for track in found:
                    track["recommendation_reason"] = f"Similar to {seed_track.get('title')} by {seed_track.get('artist')} using Last.fm"
                    track["lastfm_match"] = item.get("match")
                    candidates.append(track)


    if mode_key == "familiar" and familiar_artists:
        explanation["strategy"] = "playlist_artist_search_with_relevance_ranking"
        for artist in familiar_artists:
            artist_query = f'artist:"{artist}"'
            for track in deezer_search(artist_query, limit=max(4, count)):
                track["recommendation_reason"] = (
                    f"More music by {artist}, an artist in your playlist"
                )
                track["mode_candidate_source"] = "familiar_artist_search"
                candidates.append(track)

    # Add fallback candidates using playlist terms and user search query.
    terms = playlist_terms(playlist)
    if search_query:
        terms.extend(search_query.split())

    common_terms = Counter([term.lower() for term in terms]).most_common(6)
    explanation["search_terms"] = [term for term, _ in common_terms]

    fallback_query = search_query.strip() if search_query.strip() else " ".join(term for term, _ in common_terms[:3])
    if not fallback_query:
        fallback_query = "pop"

    for track in deezer_search(fallback_query, limit=limit):
        track["recommendation_reason"] = "Matched Deezer search terms from your playlist"
        candidates.append(track)

    # Deduplicate and remove items already in playlist/history.
    playlist_ids = {str(track.get("id")) for track in playlist}
    seen = set()
    unique_candidates = []
    for track in candidates:
        track_id = str(track.get("id"))
        if not track_id or track_id in seen or track_id in playlist_ids or track_id in history:
            continue

        candidate_artist = track.get("artist", "").strip().lower()
        if mode_key == "discover" and candidate_artist in playlist_artist_keys:
            explanation["excluded_playlist_artists"] += 1
            continue

        seen.add(track_id)
        unique_candidates.append(track)

    preferred_terms = Counter(dict(common_terms))

    # Enrich first so genre and tag evidence contributes to the final score.
    for track in unique_candidates:
        enrich_track_genres(track, fallback_query)
        score_details = score_candidate_details(
            track,
            playlist,
            preferred_terms,
            artist_bonus=mode_config["artist_bonus"],
            new_artist_bonus=mode_config["new_artist_bonus"],
        )
        track["recommendation_score"] = score_details["score"]
        track["match_score"] = score_details["match_percentage"]
        track["score_breakdown"] = {
            "matched_terms": score_details["matched_terms"],
            "artist_match": score_details["artist_match"],
            "new_artist_match": score_details["new_artist_match"],
            "artist_bonus": score_details["artist_bonus"],
            "new_artist_bonus": score_details["new_artist_bonus"],
        }
        track["recommendation_reasons"] = score_details["reasons"]
        track["recommendation_reason"] = "; ".join(score_details["reasons"])

    unique_candidates.sort(
        key=lambda item: (
            item.get("recommendation_score", 0),
            float(item.get("lastfm_match") or 0)
        ),
        reverse=True
    )

    if unique_candidates:
        ranked = diversity_rank(
            unique_candidates,
            count=count,
            max_per_artist=mode_config["max_per_artist"],
        )
        explanation["ranking_method"] = "relevance_score_with_artist_diversity"
        explanation["score_terms"] = dict(preferred_terms)
        return ranked, explanation

    # Last fallback in case the playlist/search terms are too narrow.
    fallback = [
        enrich_track_genres(track, "music")
        for track in deezer_search("music", limit=max(1, count * 2))
        if not (
            mode_key == "discover"
            and track.get("artist", "").strip().lower() in playlist_artist_keys
        )
    ][:max(1, count)]
    for track in fallback:
        track["recommendation_score"] = 0
        track["match_score"] = 0
        track["score_breakdown"] = {"matched_terms": [], "artist_match": False}
        track["recommendation_reasons"] = ["General music fallback"]
        track["recommendation_reason"] = "General music fallback"
    return fallback, explanation


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "NextTrack Deezer Last.fm MusicBrainz API"})


@app.route("/api/search")
def api_search():
    query = request.args.get("q", "").strip()
    limit = request.args.get("limit", 12, type=int)
    if not query:
        return jsonify({"tracks": [], "message": "Enter a search keyword."})

    try:
        tracks = [enrich_track_genres(track, query) for track in deezer_search(query, limit=limit)]
        return jsonify({"tracks": tracks})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/track/<track_id>")
def api_track(track_id):
    try:
        track = deezer_track(track_id)
        if not track:
            return jsonify({"error": "Track not found"}), 404
        track = enrich_track_genres(track)
        track["musicbrainz"] = musicbrainz_match(track.get("title"), track.get("artist"))
        return jsonify({"track": track})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/recommend", methods=["POST"])
def api_recommend():
    payload = request.get_json(silent=True) or {}
    playlist = payload.get("playlist", [])
    history = payload.get("history", [])
    search_query = payload.get("query", "")
    count = payload.get("count", 5)
    mode = payload.get("mode", "balanced")

    try:
        recommendations, explanation = recommend_from_playlist(
            playlist,
            history,
            search_query,
            count=count,
            mode=mode,
        )
        if not recommendations:
            return jsonify({"error": "No recommendation found"}), 404
        return jsonify({
            "recommendations": recommendations,
            "recommendation": recommendations[0],
            "based_on": {
                "playlist_size": len(playlist),
                "history_size": len(history),
                "recommendation_count": len(recommendations),
                **explanation
            }
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
