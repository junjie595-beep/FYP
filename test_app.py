import importlib.util
from collections import Counter
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

APP_PATH = Path("app.py")

spec = importlib.util.spec_from_file_location(
    "nexttrack_app",
    APP_PATH,
)

nexttrack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nexttrack)


def make_track(
    track_id,
    title,
    artist,
    album="",
    genres=None,
    preview_url="https://example.com/preview.mp3",
):
    return {
        "id": str(track_id),
        "title": title,
        "artist": artist,
        "artist_id": None,
        "album_id": None,
        "album": album,
        "cover": "",
        "duration": 30,
        "preview_url": preview_url,
        "deezer_link": "",
        "genres": genres or [],
        "source": "deezer",
    }


class NextTrackTests(unittest.TestCase):
    def setUp(self):
        nexttrack.app.config["TESTING"] = True
        self.client = nexttrack.app.test_client()
        nexttrack.CACHE.clear()

    # Test 1
    def test_health_endpoint_returns_ok(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)

        data = response.get_json()

        self.assertEqual(data["status"], "ok")
        self.assertIn("NextTrack", data["service"])

    # Test 2
    def test_empty_search_returns_helpful_message(self):
        response = self.client.get("/api/search?q=")

        self.assertEqual(response.status_code, 200)

        data = response.get_json()

        self.assertEqual(data["tracks"], [])
        self.assertEqual(
            data["message"],
            "Enter a search keyword.",
        )

    # Test 3
    @patch.object(
        nexttrack,
        "enrich_track_genres",
        side_effect=lambda track, fallback_text="": track,
    )
    @patch.object(nexttrack, "deezer_search")
    def test_search_endpoint_returns_structured_tracks(
        self,
        mock_deezer_search,
        _mock_enrich,
    ):
        mock_deezer_search.return_value = [
            make_track(
                "101",
                "Test Song",
                "Test Artist",
                "Test Album",
                ["Pop"],
            )
        ]

        response = self.client.get(
            "/api/search?q=test&limit=5"
        )

        self.assertEqual(response.status_code, 200)

        data = response.get_json()

        self.assertEqual(len(data["tracks"]), 1)
        self.assertEqual(
            data["tracks"][0]["title"],
            "Test Song",
        )
        self.assertEqual(
            data["tracks"][0]["artist"],
            "Test Artist",
        )
        self.assertEqual(
            data["tracks"][0]["genres"],
            ["Pop"],
        )

    # Test 4
    def test_normalise_deezer_track_returns_expected_fields(self):
        raw_track = {
            "id": 123,
            "title": "Example Song",
            "artist": {
                "id": 10,
                "name": "Example Artist",
            },
            "album": {
                "id": 20,
                "title": "Example Album",
                "cover_medium": "cover.jpg",
            },
            "duration": 180,
            "preview": "preview.mp3",
            "link": "deezer-link",
        }

        track = nexttrack.normalise_deezer_track(
            raw_track
        )

        self.assertEqual(track["id"], "123")
        self.assertEqual(
            track["title"],
            "Example Song",
        )
        self.assertEqual(
            track["artist"],
            "Example Artist",
        )
        self.assertEqual(
            track["album"],
            "Example Album",
        )
        self.assertEqual(
            track["preview_url"],
            "preview.mp3",
        )
        self.assertEqual(track["source"], "deezer")

    # Test 5
    def test_tag_cleaning_removes_blocked_and_long_values(self):
        self.assertEqual(
            nexttrack.clean_tag("spotify"),
            "",
        )
        self.assertEqual(
            nexttrack.clean_tag("seen live"),
            "",
        )
        self.assertEqual(
            nexttrack.clean_tag("rock"),
            "Rock",
        )
        self.assertEqual(
            nexttrack.clean_tag("x" * 29),
            "",
        )

    # Test 6
    def test_fallback_genres_detects_known_terms(self):
        genres = nexttrack.fallback_genres_from_text(
            "Energetic rock and electronic music"
        )

        self.assertIn("Rock", genres)
        self.assertIn("Electronic", genres)
        self.assertIn("Energetic", genres)

    # Test 7
    def test_playlist_terms_extracts_artist_album_genre_and_title(self):
        playlist = [
            make_track(
                "1",
                "Great Rock Song",
                "Artist A",
                "Album A",
                ["Rock"],
            )
        ]

        terms = nexttrack.playlist_terms(playlist)

        lowered_terms = [
            str(term).lower()
            for term in terms
        ]

        self.assertIn("artist a", lowered_terms)
        self.assertIn("album a", lowered_terms)
        self.assertIn("rock", lowered_terms)
        self.assertIn("great", lowered_terms)
        self.assertIn("song", lowered_terms)

    # Test 8
    def test_score_candidate_rewards_playlist_matches(self):
        playlist = [
            make_track(
                "1",
                "First Song",
                "Artist A",
                "Album A",
                ["Rock"],
            ),
            make_track(
                "2",
                "Second Song",
                "Artist A",
                "Album B",
                ["Rock"],
            ),
        ]

        preferred_terms = Counter({
            "rock": 2,
            "artist a": 2,
        })

        strong_candidate = make_track(
            "10",
            "Another Rock Song",
            "Artist A",
            "New Album",
            ["Rock"],
        )

        weak_candidate = make_track(
            "11",
            "Quiet Piano",
            "Artist B",
            "Different Album",
            ["Classical"],
        )

        strong_score = nexttrack.score_candidate(
            strong_candidate,
            playlist,
            preferred_terms,
        )

        weak_score = nexttrack.score_candidate(
            weak_candidate,
            playlist,
            preferred_terms,
        )

        self.assertGreater(
            strong_score,
            weak_score,
        )
        self.assertEqual(strong_score, 6)
        self.assertEqual(weak_score, 0)

    # Test 9
    def test_score_details_explain_matches_and_percentage(self):
        playlist = [
            make_track(
                "1",
                "Rock Song",
                "Artist A",
                "Album A",
                ["Rock"],
            )
        ]

        preferred_terms = Counter({
            "rock": 2,
            "artist a": 1,
        })

        candidate = make_track(
            "10",
            "Another Rock Song",
            "Artist A",
            "New Album",
            ["Rock"],
        )

        details = nexttrack.score_candidate_details(
            candidate,
            playlist,
            preferred_terms,
        )

        self.assertEqual(details["score"], 5)
        self.assertEqual(
            details["match_percentage"],
            100,
        )
        self.assertTrue(details["artist_match"])

        self.assertIn(
            "Artist already appears in your playlist",
            details["reasons"],
        )

        matched_names = [
            item["term"]
            for item in details["matched_terms"]
        ]

        self.assertIn("Rock", matched_names)
        self.assertIn("Artist A", matched_names)

    # Test 10
    def test_artist_match_adds_two_points_in_balanced_mode(self):
        playlist = [
            make_track(
                "1",
                "Song",
                "Artist A",
            )
        ]

        preferred_terms = Counter()

        same_artist = make_track(
            "2",
            "Different Song",
            "Artist A",
        )

        other_artist = make_track(
            "3",
            "Different Song",
            "Artist B",
        )

        same_score = nexttrack.score_candidate(
            same_artist,
            playlist,
            preferred_terms,
        )

        other_score = nexttrack.score_candidate(
            other_artist,
            playlist,
            preferred_terms,
        )

        self.assertEqual(same_score, 2)
        self.assertEqual(other_score, 0)

    # Test 11
    def test_familiar_mode_has_expected_settings(self):
        mode_name, settings = (
            nexttrack.recommendation_mode("familiar")
        )

        self.assertEqual(mode_name, "familiar")
        self.assertEqual(
            settings["label"],
            "Familiar",
        )
        self.assertEqual(
            settings["artist_bonus"],
            4,
        )
        self.assertEqual(
            settings["new_artist_bonus"],
            0,
        )
        self.assertEqual(
            settings["max_per_artist"],
            3,
        )

    # Test 12
    def test_balanced_mode_has_expected_settings(self):
        mode_name, settings = (
            nexttrack.recommendation_mode("balanced")
        )

        self.assertEqual(mode_name, "balanced")
        self.assertEqual(
            settings["label"],
            "Balanced",
        )
        self.assertEqual(
            settings["artist_bonus"],
            2,
        )
        self.assertEqual(
            settings["new_artist_bonus"],
            0,
        )
        self.assertEqual(
            settings["max_per_artist"],
            2,
        )

    # Test 13
    def test_discover_mode_has_expected_settings(self):
        mode_name, settings = (
            nexttrack.recommendation_mode("discover")
        )

        self.assertEqual(mode_name, "discover")
        self.assertEqual(
            settings["label"],
            "Discover",
        )
        self.assertEqual(
            settings["artist_bonus"],
            0,
        )
        self.assertEqual(
            settings["new_artist_bonus"],
            2,
        )
        self.assertEqual(
            settings["max_per_artist"],
            1,
        )

    # Test 14
    def test_invalid_mode_defaults_to_balanced(self):
        mode_name, settings = (
            nexttrack.recommendation_mode(
                "not-a-real-mode"
            )
        )

        self.assertEqual(mode_name, "balanced")
        self.assertEqual(
            settings["label"],
            "Balanced",
        )

    # Test 15
    def test_diversity_rank_limits_repeated_artists(self):
        candidates = [
            make_track(
                "1",
                "Song One",
                "Artist A",
            ),
            make_track(
                "2",
                "Song Two",
                "Artist A",
            ),
            make_track(
                "3",
                "Song Three",
                "Artist A",
            ),
            make_track(
                "4",
                "Song Four",
                "Artist B",
            ),
            make_track(
                "5",
                "Song Five",
                "Artist C",
            ),
        ]

        ranked = nexttrack.diversity_rank(
            candidates,
            count=5,
            max_per_artist=2,
        )

        artist_counts = Counter(
            track["artist"]
            for track in ranked
        )

        self.assertLessEqual(
            artist_counts["Artist A"],
            2,
        )
        self.assertIn("Artist B", artist_counts)
        self.assertIn("Artist C", artist_counts)

    # Test 16
    def test_diversity_rank_strictly_limits_each_artist(self):
        candidates = [
            make_track(
                "1",
                "Song One",
                "Artist A",
            ),
            make_track(
                "2",
                "Song Two",
                "Artist A",
            ),
            make_track(
                "3",
                "Song Three",
                "Artist B",
            ),
            make_track(
                "4",
                "Song Four",
                "Artist C",
            ),
        ]

        ranked = nexttrack.diversity_rank(
            candidates,
            count=4,
            max_per_artist=1,
        )

        artists = [
            track["artist"]
            for track in ranked
        ]

        artist_counts = Counter(artists)

        self.assertEqual(len(ranked), 3)
        self.assertEqual(
            artist_counts["Artist A"],
            1,
        )
        self.assertTrue(
            all(
                count == 1
                for count in artist_counts.values()
            )
        )

    # Test 17
    @patch.object(
        nexttrack,
        "enrich_track_genres",
        side_effect=lambda track, fallback_text="": track,
    )
    @patch.object(
        nexttrack,
        "musicbrainz_match",
        return_value=None,
    )
    @patch.object(
        nexttrack,
        "lastfm_similar_tracks",
    )
    @patch.object(
        nexttrack,
        "deezer_search",
    )
    def test_recommendation_filters_playlist_history_and_duplicates(
        self,
        mock_deezer_search,
        mock_similar,
        _mock_mb,
        _mock_enrich,
    ):
        playlist = [
            make_track(
                "1",
                "Seed Song",
                "Artist A",
                "Album A",
                ["Rock"],
            )
        ]

        history = ["3"]

        mock_similar.return_value = [
            {
                "title": "Candidate One",
                "artist": "Artist B",
                "match": "0.9",
            },
            {
                "title": "Candidate Two",
                "artist": "Artist C",
                "match": "0.8",
            },
        ]

        candidate_2 = make_track(
            "2",
            "Candidate One",
            "Artist B",
            "Album B",
            ["Rock"],
        )

        candidate_3 = make_track(
            "3",
            "Candidate Two",
            "Artist C",
            "Album C",
            ["Rock"],
        )

        duplicate_2 = make_track(
            "2",
            "Candidate One",
            "Artist B",
            "Album B",
            ["Rock"],
        )

        already_in_playlist = make_track(
            "1",
            "Seed Song",
            "Artist A",
            "Album A",
            ["Rock"],
        )

        fallback_4 = make_track(
            "4",
            "Fresh Rock Track",
            "Artist D",
            "Album D",
            ["Rock"],
        )

        def fake_deezer_search(query, limit=12):
            if "Candidate One" in query:
                return [candidate_2]

            if "Candidate Two" in query:
                return [candidate_3]

            return [
                duplicate_2,
                already_in_playlist,
                fallback_4,
            ]

        mock_deezer_search.side_effect = (
            fake_deezer_search
        )

        recommendations, explanation = (
            nexttrack.recommend_from_playlist(
                playlist,
                history=history,
                search_query="",
                count=5,
            )
        )

        returned_ids = [
            track["id"]
            for track in recommendations
        ]

        self.assertIn("2", returned_ids)
        self.assertIn("4", returned_ids)
        self.assertNotIn("1", returned_ids)
        self.assertNotIn("3", returned_ids)
        self.assertEqual(
            returned_ids.count("2"),
            1,
        )
        self.assertTrue(
            explanation["used_lastfm"]
        )

    # Test 18
    @patch.object(
        nexttrack,
        "recommend_from_playlist",
    )
    def test_recommend_endpoint_returns_multiple_results(
        self,
        mock_recommend,
    ):
        mock_recommend.return_value = (
            [
                make_track(
                    "10",
                    "Song A",
                    "Artist A",
                ),
                make_track(
                    "11",
                    "Song B",
                    "Artist B",
                ),
            ],
            {
                "strategy": "test_strategy",
                "seed_track": {
                    "id": "1",
                    "title": "Seed",
                    "artist": "Seed Artist",
                },
                "used_lastfm": True,
                "used_musicbrainz": False,
                "search_terms": ["rock"],
                "recommendation_mode": "balanced",
                "recommendation_mode_label": "Balanced",
                "artist_bonus": 2,
                "new_artist_bonus": 0,
                "maximum_tracks_per_artist": 2,
                "excluded_playlist_artists": 0,
                "familiar_artists": [
                    "Seed Artist"
                ],
            },
        )

        payload = {
            "playlist": [
                make_track(
                    "1",
                    "Seed",
                    "Seed Artist",
                )
            ],
            "history": [],
            "query": "rock",
            "count": 2,
            "mode": "balanced",
        }

        response = self.client.post(
            "/api/recommend",
            json=payload,
        )

        self.assertEqual(response.status_code, 200)

        data = response.get_json()

        self.assertEqual(
            len(data["recommendations"]),
            2,
        )
        self.assertEqual(
            data["recommendation"]["id"],
            "10",
        )
        self.assertEqual(
            data["based_on"][
                "recommendation_count"
            ],
            2,
        )
        self.assertEqual(
            data["based_on"]["strategy"],
            "test_strategy",
        )
        self.assertEqual(
            data["based_on"][
                "recommendation_mode"
            ],
            "balanced",
        )

    # Test 19
    @patch.object(
        nexttrack,
        "deezer_track",
        return_value=None,
    )
    def test_missing_track_returns_404(
        self,
        _mock_track,
    ):
        response = self.client.get(
            "/api/track/999999"
        )

        self.assertEqual(
            response.status_code,
            404,
        )

        data = response.get_json()

        self.assertEqual(
            data["error"],
            "Track not found",
        )

    # Test 20
    @patch.object(nexttrack.session, "get")
    def test_cached_get_reuses_saved_response(
        self,
        mock_get,
    ):
        mock_response = Mock()
        mock_response.json.return_value = {
            "value": "test-data"
        }
        mock_response.raise_for_status.return_value = (
            None
        )

        mock_get.return_value = mock_response

        first_result = nexttrack.cached_get(
            "https://example.com/test",
            {"q": "rock"},
        )

        second_result = nexttrack.cached_get(
            "https://example.com/test",
            {"q": "rock"},
        )

        self.assertEqual(
            first_result,
            {"value": "test-data"},
        )
        self.assertEqual(
            second_result,
            {"value": "test-data"},
        )
        self.assertEqual(
            mock_get.call_count,
            1,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)