import xml.etree.ElementTree as ET
import pytest
from castcast.mediaserver import transform_peacock_dash_manifest

SAMPLE_PEACOCK_MPD = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" minBufferTime="PT2S" type="static">
  <Period id="ad_period_pre_roll" start="PT0S" duration="PT189S">
    <EventStream schemeIdUri="urn:psf:ads:tracking:v1" value="1"/>
    <AdaptationSet mimeType="video/mp4" contentType="video">
      <Representation id="ad_video" bandwidth="2000000"/>
    </AdaptationSet>
  </Period>
  <Period id="feature_movie_period" start="PT189S" duration="PT8243S">
    <AdaptationSet mimeType="video/mp4" contentType="video">
      <ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/>
      <Representation id="feature_video_4k" bandwidth="15000000" width="3840" height="2160"/>
    </AdaptationSet>
  </Period>
</MPD>"""


def test_transform_peacock_dash_manifest_strips_ads():
    target_url = "https://g002-vod-us-cmaf-prd-cc.cdn.peacocktv.com/path/manifest.mpd"
    transformed = transform_peacock_dash_manifest(SAMPLE_PEACOCK_MPD, target_url)

    assert "ad_period_pre_roll" not in transformed
    assert "urn:psf:ads:tracking:v1" not in transformed
    assert "feature_movie_period" in transformed
    assert 'width="3840"' in transformed
    assert 'height="2160"' in transformed
    assert 'start="PT0S"' in transformed or 'start="PT0.000S"' in transformed
    assert "<BaseURL>https://g002-vod-us-cmaf-prd-cc.cdn.peacocktv.com/path/</BaseURL>" in transformed
    assert 'schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"' in transformed


def test_transform_peacock_dash_manifest_multi_period_ad_stripping():
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
  <Period id="ad_pre" start="PT0S" duration="PT30S">
    <EventStream schemeIdUri="urn:scte:scte35:2014:bin"/>
  </Period>
  <Period id="feature_part_1" start="PT30S" duration="PT600S">
    <AdaptationSet mimeType="video/mp4">
      <ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/>
      <Representation id="v1" width="3840" height="2160"/>
    </AdaptationSet>
  </Period>
  <Period id="midroll_1" start="PT630S" duration="PT45S">
    <EventStream schemeIdUri="urn:sva:advertising-wg:ad-id-signaling"/>
  </Period>
  <Period id="feature_part_2" start="PT675S" duration="PT600S">
    <AdaptationSet mimeType="video/mp4">
      <ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/>
      <Representation id="v2" width="3840" height="2160"/>
    </AdaptationSet>
  </Period>
  <Period id="ad_post" start="PT1275S" duration="PT15S"/>
</MPD>"""
    target_url = "https://vod.peacocktv.com/asset/index.mpd"
    transformed = transform_peacock_dash_manifest(manifest, target_url)

    assert "ad_pre" not in transformed
    assert "midroll_1" not in transformed
    assert "ad_post" not in transformed
    assert "urn:scte:scte35:2014:bin" not in transformed
    assert "urn:sva:advertising-wg:ad-id-signaling" not in transformed

    assert "feature_part_1" in transformed
    assert "feature_part_2" in transformed
    # Primary feature period re-based to PT0S
    assert 'id="feature_part_1" start="PT0S"' in transformed or ('id="feature_part_1"' in transformed and 'start="PT0S"' in transformed)


def test_transform_peacock_dash_manifest_id_case_insensitive_matching():
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period id="AD_BREAK_1" start="PT0S" duration="PT15S"/>
  <Period id="episode_content" start="PT15S" duration="PT1200S">
    <AdaptationSet mimeType="video/mp4">
      <Representation id="v_uhd" width="3840" height="2160"/>
    </AdaptationSet>
  </Period>
  <Period id="PostRoll-Ad" start="PT1215S" duration="PT15S"/>
</MPD>"""
    transformed = transform_peacock_dash_manifest(manifest, "https://peacocktv.com/dash/video.mpd")
    assert "AD_BREAK_1" not in transformed
    assert "PostRoll-Ad" not in transformed
    assert "episode_content" in transformed
    assert 'start="PT0S"' in transformed


def test_transform_peacock_dash_manifest_detects_ad_by_event_schemes_without_ad_in_id():
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period id="p0" start="PT0S" duration="PT30S">
    <EventStream schemeIdUri="urn:psf:ads:tracking:v1"/>
  </Period>
  <Period id="p1" start="PT30S" duration="PT1000S">
    <AdaptationSet mimeType="video/mp4">
      <Representation id="v" width="1920" height="1080"/>
    </AdaptationSet>
  </Period>
</MPD>"""
    transformed = transform_peacock_dash_manifest(manifest, "https://peacocktv.com/dash/video.mpd")
    assert 'id="p0"' not in transformed
    assert 'id="p1"' in transformed
    assert 'start="PT0S"' in transformed


def test_transform_peacock_dash_manifest_preserves_existing_base_url():
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <BaseURL>https://existing.cdn.peacocktv.com/vod/</BaseURL>
  <Period id="main" start="PT0S">
    <AdaptationSet mimeType="video/mp4">
      <Representation id="v" width="3840" height="2160"/>
    </AdaptationSet>
  </Period>
</MPD>"""
    transformed = transform_peacock_dash_manifest(manifest, "https://other.cdn.peacocktv.com/different/path/manifest.mpd")
    assert "https://existing.cdn.peacocktv.com/vod/" in transformed
    assert transformed.count("<BaseURL>") == 1
    assert "https://other.cdn.peacocktv.com/different/path/" not in transformed


def test_transform_peacock_dash_manifest_namespace_and_cenc_preservation():
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" xmlns:cenc="urn:mpeg:cenc:2013">
  <Period id="ad1" start="PT0S">
    <EventStream schemeIdUri="urn:psf:ads:tracking:v1"/>
  </Period>
  <Period id="feature" start="PT30S">
    <AdaptationSet mimeType="video/mp4">
      <ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed" cenc:default_KID="4a821e28-761a-42c2-8495-2d4df55bb391"/>
      <Representation id="v_4k" width="3840" height="2160"/>
    </AdaptationSet>
  </Period>
</MPD>"""
    transformed = transform_peacock_dash_manifest(manifest, "https://cdn.peacocktv.com/vod/stream.mpd")
    assert "urn:mpeg:dash:schema:mpd:2011" in transformed
    assert 'cenc:default_KID="4a821e28-761a-42c2-8495-2d4df55bb391"' in transformed
    assert "ad1" not in transformed
    assert "feature" in transformed


def test_transform_peacock_dash_manifest_regex_fallback_on_malformed_xml():
    # Intentionally malformed XML that fails ET.fromstring
    malformed_manifest = """<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period id="ad_broken" start="PT0S" duration="PT30S">
    <EventStream schemeIdUri="urn:psf:ads:tracking:v1">
  </Period>
  <Period id="feature_broken" start="PT30S" duration="PT1000S">
    <AdaptationSet mimeType="video/mp4">
      <ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/>
      <Representation id="v4k" width="3840" height="2160"/>
    </AdaptationSet>
  </Period>
</MPD>"""
    transformed = transform_peacock_dash_manifest(malformed_manifest, "https://cdn.peacocktv.com/vod/stream.mpd")
    assert "ad_broken" not in transformed
    assert "feature_broken" in transformed
    assert 'width="3840"' in transformed
    assert 'height="2160"' in transformed
    assert '<BaseURL>https://cdn.peacocktv.com/vod/</BaseURL>' in transformed
    assert 'schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"' in transformed
