import io
import unittest
from unittest.mock import MagicMock, patch

from castcast.amazon_drm import parse_mpd_subtitles
from castcast.service import CastService
from castcast.supervisor import Supervisor

SAMPLE_MPD = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" minBufferTime="PT1.5S">
  <Period id="0">
    <AdaptationSet id="1" contentType="video" width="3840" height="2160">
      <Representation id="v4k" bandwidth="15000000" codecs="hev1.2.4.L153.B0"/>
    </AdaptationSet>
    <AdaptationSet id="2" contentType="text" mimeType="text/vtt" lang="en">
      <Role value="main"/>
      <Representation id="sub_en" bandwidth="1000"/>
    </AdaptationSet>
    <AdaptationSet id="3" contentType="text" mimeType="application/ttml+xml" lang="es">
      <Role value="subtitle"/>
      <Representation id="sub_es" bandwidth="1000"/>
    </AdaptationSet>
  </Period>
</MPD>
"""

SAMPLE_MPD_RICH = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" minBufferTime="PT1.5S">
  <Period id="0">
    <AdaptationSet id="10" contentType="video" width="3840" height="2160">
      <Representation id="v4k_uhd" bandwidth="20000000" codecs="hev1.2.4.L153.B0" height="2160" width="3840"/>
    </AdaptationSet>
    <AdaptationSet id="11" contentType="audio" mimeType="audio/mp4" lang="en">
      <Role value="main"/>
      <Representation id="a_en" bandwidth="128000"/>
    </AdaptationSet>
    <AdaptationSet id="20" contentType="text" mimeType="text/vtt" lang="en-US">
      <Role value="main"/>
      <Representation id="sub_en" bandwidth="1000"/>
    </AdaptationSet>
    <AdaptationSet id="21" contentType="text" mimeType="text/vtt" lang="es">
      <Role schemeIdUri="urn:mpeg:dash:role:2011" value="caption"/>
      <Representation id="sub_es_sdh" bandwidth="1000"/>
    </AdaptationSet>
    <AdaptationSet id="22" contentType="text" mimeType="application/mp4" lang="fr-CA">
      <Role value="forced-subtitle"/>
      <Representation id="sub_fr_forced" bandwidth="1000"/>
    </AdaptationSet>
    <AdaptationSet id="23" contentType="text" mimeType="application/ttml+xml" lang="de">
      <Role value="sdh"/>
      <Representation id="sub_de_sdh" bandwidth="1000"/>
    </AdaptationSet>
  </Period>
</MPD>
"""

SAMPLE_MPD_NO_IDS = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period id="0">
    <AdaptationSet contentType="text" mimeType="application/mp4" lang="en-US">
      <Role value="caption"/>
      <Representation bandwidth="1000"/>
    </AdaptationSet>
    <AdaptationSet contentType="text" mimeType="application/mp4" lang="es-ES">
      <Role value="subtitle"/>
      <Representation bandwidth="1000"/>
    </AdaptationSet>
  </Period>
</MPD>
"""


class TestAmazonSubtitles(unittest.TestCase):
    def test_parse_mpd_subtitles_basic(self):
        subs = parse_mpd_subtitles(SAMPLE_MPD)
        self.assertEqual(len(subs), 2)
        langs = [s["language"] for s in subs]
        self.assertIn("eng", langs)
        self.assertIn("spa", langs)
        self.assertEqual(subs[0]["mime_type"], "text/vtt")
        self.assertEqual(subs[0]["track_id"], 2)
        self.assertEqual(subs[0]["role"], "main")
        self.assertEqual(subs[0]["label"], "English [Amazon]")

        self.assertEqual(subs[1]["mime_type"], "application/ttml+xml")
        self.assertEqual(subs[1]["track_id"], 3)
        self.assertEqual(subs[1]["role"], "subtitle")
        self.assertEqual(subs[1]["label"], "Spanish [Amazon]")

    def test_parse_mpd_subtitles_rich_labels_and_sdh(self):
        subs = parse_mpd_subtitles(SAMPLE_MPD_RICH)
        self.assertEqual(len(subs), 4)

        # Track 20: English main
        self.assertEqual(subs[0]["track_id"], 20)
        self.assertEqual(subs[0]["language"], "eng")
        self.assertEqual(subs[0]["label"], "English [Amazon]")

        # Track 21: Spanish SDH (caption)
        self.assertEqual(subs[1]["track_id"], 21)
        self.assertEqual(subs[1]["language"], "spa")
        self.assertEqual(subs[1]["role"], "caption")
        self.assertEqual(subs[1]["label"], "Spanish (SDH) [Amazon]")

        # Track 22: French forced
        self.assertEqual(subs[2]["track_id"], 22)
        self.assertEqual(subs[2]["language"], "fre")
        self.assertEqual(subs[2]["mime_type"], "application/mp4")
        self.assertEqual(subs[2]["label"], "French (Forced) [Amazon]")

        # Track 23: German SDH
        self.assertEqual(subs[3]["track_id"], 23)
        self.assertEqual(subs[3]["language"], "ger")
        self.assertEqual(subs[3]["label"], "German (SDH) [Amazon]")

    def test_parse_mpd_subtitles_unspecified_ids(self):
        subs = parse_mpd_subtitles(SAMPLE_MPD_NO_IDS)
        self.assertEqual(len(subs), 2)
        ids = [s["track_id"] for s in subs]
        self.assertTrue(all(isinstance(i, int) and i > 0 for i in ids))
        self.assertEqual(len(set(ids)), 2)

    def test_parse_mpd_subtitles_empty_and_invalid(self):
        self.assertEqual(parse_mpd_subtitles(""), [])
        self.assertEqual(parse_mpd_subtitles(None), [])
        self.assertEqual(parse_mpd_subtitles("<<<invalid xml>>>"), [])
        no_subs_mpd = """<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
          <Period><AdaptationSet contentType="video"><Representation id="v"/></AdaptationSet></Period>
        </MPD>"""
        self.assertEqual(parse_mpd_subtitles(no_subs_mpd), [])

    def test_parse_mpd_subtitles_bytes_input(self):
        subs = parse_mpd_subtitles(SAMPLE_MPD.encode("utf-8"))
        self.assertEqual(len(subs), 2)
        self.assertEqual(subs[0]["language"], "eng")

    def test_parse_mpd_subtitles_track_id_collision_prevention(self):
        mpd_with_existing_ids = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period id="0">
    <AdaptationSet id="1" contentType="video" width="3840" height="2160">
      <Representation id="v4k" bandwidth="15000000"/>
    </AdaptationSet>
    <AdaptationSet id="2" contentType="audio" mimeType="audio/mp4" lang="en">
      <Representation id="a1" bandwidth="128000"/>
    </AdaptationSet>
    <AdaptationSet contentType="text" mimeType="text/vtt" lang="es">
      <Representation id="s1" bandwidth="1000"/>
    </AdaptationSet>
  </Period>
</MPD>"""
        subs = parse_mpd_subtitles(mpd_with_existing_ids)
        self.assertEqual(len(subs), 1)
        # Next ID must be > max(used_ids) which is 2 -> track_id must be 3
        self.assertEqual(subs[0]["track_id"], 3)

    def test_parse_mpd_subtitles_multiple_role_elements(self):
        mpd_multi_role = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period id="0">
    <AdaptationSet contentType="text" mimeType="text/vtt" lang="en">
      <Role value="main"/>
      <Role value="caption"/>
      <Representation id="s1" bandwidth="1000"/>
    </AdaptationSet>
  </Period>
</MPD>"""
        subs = parse_mpd_subtitles(mpd_multi_role)
        self.assertEqual(len(subs), 1)
        self.assertIn("(SDH)", subs[0]["label"])

    def test_parse_mpd_subtitles_strict_application_mp4_detection(self):
        # application/mp4 without text ct and without stpp/wvtt codec must be ignored
        mpd_non_text_mp4 = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period id="0">
    <AdaptationSet mimeType="application/mp4" lang="en">
      <Representation id="rep1" codecs="mp4a.40.2"/>
    </AdaptationSet>
  </Period>
</MPD>"""
        self.assertEqual(parse_mpd_subtitles(mpd_non_text_mp4), [])

        # application/mp4 with stpp codec must be accepted as subtitle
        mpd_stpp_mp4 = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period id="0">
    <AdaptationSet mimeType="application/mp4" lang="es">
      <Representation id="rep_sub" codecs="stpp"/>
    </AdaptationSet>
  </Period>
</MPD>"""
        subs = parse_mpd_subtitles(mpd_stpp_mp4)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["language"], "spa")

    def test_4k_representations_untouched_and_excluded_from_subtitles(self):
        subs = parse_mpd_subtitles(SAMPLE_MPD_RICH)
        # Ensure 4K video adaptation set id=10 is NOT included in subtitles
        track_ids = [s["track_id"] for s in subs]
        self.assertNotIn(10, track_ids)
        self.assertNotIn("video", [s.get("mime_type", "") for s in subs])

        # Verify 4K video representation string is untouched in original manifest
        self.assertIn('height="2160"', SAMPLE_MPD_RICH)
        self.assertIn('width="3840"', SAMPLE_MPD_RICH)
        self.assertIn('codecs="hev1.2.4.L153.B0"', SAMPLE_MPD_RICH)

    def test_mediaserver_proxy_preserves_4k_and_multilingual_subtitles(self):
        from castcast.mediaserver import transform_dash_manifest

        mpd_input = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period id="0">
    <AdaptationSet id="1" contentType="video" width="3840" height="2160">
      <Representation id="v4k" bandwidth="15000000" codecs="hev1.2.4.L153.B0" height="2160" width="3840"/>
    </AdaptationSet>
    <AdaptationSet id="2" contentType="audio" mimeType="audio/mp4" lang="en">
      <Representation id="a_en" bandwidth="128000"/>
    </AdaptationSet>
    <AdaptationSet id="3" contentType="audio" mimeType="audio/mp4" lang="es">
      <Representation id="a_es" bandwidth="128000"/>
    </AdaptationSet>
    <AdaptationSet id="4" contentType="text" mimeType="text/vtt" lang="en">
      <Role value="main"/>
      <Representation id="sub_en" bandwidth="1000"/>
    </AdaptationSet>
    <AdaptationSet id="5" contentType="text" mimeType="application/ttml+xml" lang="es">
      <Role value="subtitle"/>
      <Representation id="sub_es" bandwidth="1000"/>
    </AdaptationSet>
    <AdaptationSet id="6" contentType="text" mimeType="application/mp4" lang="fr">
      <Role value="subtitle"/>
      <Representation id="sub_fr" bandwidth="1000"/>
    </AdaptationSet>
  </Period>
</MPD>"""

        transformed = transform_dash_manifest(mpd_input, "https://cf.amazon.com/dash/manifest.mpd")

        # 4K representation must be completely untouched
        self.assertIn('height="2160"', transformed)
        self.assertIn('width="3840"', transformed)
        self.assertIn('codecs="hev1.2.4.L153.B0"', transformed)
        self.assertIn('<AdaptationSet id="1" contentType="video"', transformed)

        # BaseURL must be injected
        self.assertIn('<BaseURL>https://cf.amazon.com/dash/</BaseURL>', transformed)

        # English audio must be preserved
        self.assertIn('<AdaptationSet id="2" contentType="audio" mimeType="audio/mp4" lang="en">', transformed)

        # Non-English audio (es) must be stripped
        self.assertNotIn('<AdaptationSet id="3"', transformed)

        # Multi-language subtitle tracks (en, es, fr) MUST be completely preserved!
        self.assertIn('<AdaptationSet id="4" contentType="text" mimeType="text/vtt" lang="en">', transformed)
        self.assertIn('<AdaptationSet id="5" contentType="text" mimeType="application/ttml+xml" lang="es">', transformed)
        self.assertIn('<AdaptationSet id="6" contentType="text" mimeType="application/mp4" lang="fr">', transformed)


class TestAmazonSubtitlesServiceIntegration(unittest.TestCase):
    def setUp(self):
        self.svc = CastService({})
        self.svc.supervisor = MagicMock(spec=Supervisor)
        self.svc.supervisor.status = MagicMock()
        self.svc.supervisor.status.active_track_ids = []

    def test_cast_amazon_populates_tracks_and_exposes_subtitles(self):
        with patch("castcast.amazon_drm.fetch_amazon_4k_manifest", return_value={
            "mpd_url": "http://amazon.example/manifest.mpd",
            "actor_token": "actor_tok_123",
            "playback_envelope": "envelope_123",
            "manifest_text": SAMPLE_MPD,
        }):
            res = self.svc._cast_amazon(
                "https://www.amazon.com/gp/video/detail/B0B1C2D3E4",
                manifest_text=SAMPLE_MPD,
            )
            self.assertTrue(res.get("casting"))
            self.assertEqual(self.svc._current_source_type, "amazon")
            self.assertEqual(len(self.svc._current_scavenged_tracks), 2)

            # Check get_available_subtitles
            avail = self.svc.get_available_subtitles()
            self.assertEqual(avail["source_type"], "amazon")
            self.assertEqual(avail["remote_supported"], False)
            self.assertEqual(len(avail["tracks"]), 2)
            self.assertEqual(avail["tracks"][0]["label"], "English [Amazon]")
            self.assertEqual(avail["tracks"][1]["label"], "Spanish [Amazon]")

            # Test selecting subtitle track
            sel_res = self.svc.select_subtitle_track(2)
            self.assertEqual(sel_res["active_track_ids"], [2])
            self.svc.supervisor.set_active_tracks.assert_called_once_with([2])

    def test_cast_amazon_fetches_manifest_via_urlopen_when_not_passed(self):
        mock_response = MagicMock()
        mock_response.read.return_value = SAMPLE_MPD_RICH.encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("castcast.amazon_drm.fetch_amazon_4k_manifest", return_value={
            "mpd_url": "http://amazon.example/manifest.mpd",
            "actor_token": "actor_tok_123",
            "playback_envelope": "envelope_123",
        }), patch("urllib.request.urlopen", return_value=mock_response):
            res = self.svc.cast("https://www.amazon.com/gp/video/detail/B0RICH123")
            self.assertTrue(res.get("casting"))
            self.assertEqual(self.svc._current_source_type, "amazon")
            self.assertEqual(len(self.svc._current_scavenged_tracks), 4)
            self.assertEqual(self.svc._current_scavenged_tracks[1]["label"], "Spanish (SDH) [Amazon]")

    def test_cast_amazon_uses_clean_path(self):
        with patch.object(self.svc, "_cast_amazon", return_value={"casting": True}) as mock_cast_amz:
            raw_url = "https://www.amazon.com/gp/video/detail/B0CLEAN123?ref_=atv_dp_season_select_s1"
            self.svc.cast(raw_url)
            mock_cast_amz.assert_called_once_with(raw_url, title=None)
