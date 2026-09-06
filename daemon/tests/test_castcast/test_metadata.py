import pytest
import base64
from unittest.mock import patch, MagicMock
from castcast.metadata import resolve_title, _clean_title, clear_amazon_cache

@pytest.fixture(autouse=True)
def reset_amazon_cache():
    clear_amazon_cache()
    yield
    clear_amazon_cache()

class TestMetadataTier1:
    @patch('urllib.request.urlopen')
    def test_amazon_gti_extraction(self, mock_urlopen):
        # Mock the HTML response for an Amazon detail page
        mock_html = b"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Prime Video: Hazbin Hotel - Season 2</title>
        </head>
        <body>...</body>
        </html>
        """
        mock_response = MagicMock()
        mock_response.read.return_value = mock_html
        mock_urlopen.return_value = mock_response

        # Given an Amazon GTI URL
        url = "https://www.primevideo.com/detail?gti=amzn1.dv.gti.2a50e5b4-edfb-47c8-9b71-72d085008f16"
        
        # When resolved
        title = resolve_title(url, provider="amazon")

        # Then the SEO prefixes are stripped and the clean title is returned
        assert title == "Hazbin Hotel - Season 2"
        mock_urlopen.assert_called_once()

    @patch('urllib.request.urlopen')
    def test_amazon_gti_extraction_alternate_prefix(self, mock_urlopen):
        # Mock another variant of the title
        mock_html = b"<title>Watch The Boys Season 4 | Prime Video</title>"
        mock_response = MagicMock()
        mock_response.read.return_value = mock_html
        mock_urlopen.return_value = mock_response

        title = resolve_title("amzn1.dv.gti.12345", provider="amazon")
        # Should strip "Watch " and " | Prime Video"
        assert title == "The Boys Season 4"


class TestMetadataTier2:
    def test_base64_proxy_payload_fallback(self):
        # A Base64 encoded proxy payload for an MPD manifest
        # Decodes to: https://cdn.net/.../87dbf26a-8f56-4432-bbae-3de3266cf490_Proj_S01_E04_4K.mpd
        mpd_url = "https://cdn.net/path/to/87dbf26a-8f56-4432-bbae-3de3266cf490_Proj_S01_E04_4K.mpd"
        b64_payload = base64.b64encode(mpd_url.encode('utf-8')).decode('utf-8')
        proxy_url = f"http://192.168.1.27:43753/proxy/?url={b64_payload}"

        title = resolve_title(proxy_url)
        
        # Should decode base64, extract the filename, and perhaps clean the UUID / 4K
        # The exact implementation of cleaning UUIDs is up to the regex, but it should at least extract the filename
        # and strip the extension and "4K"
        assert "Proj_S01_E04" in title
        assert ".mpd" not in title
        assert "4K" not in title.upper()


class TestTitleCleaning:
    def test_pollution_stripping(self):
        assert _clean_title("My Movie 1080p BluRay x264") == "My Movie"
        assert _clean_title("Some Show S01E05 720p WEBRip") == "Some Show S01E05"
        assert _clean_title("Watch Some Movie | Prime Video") == "Some Movie"
        assert _clean_title("Prime Video: Another Show") == "Another Show"

class TestMetadataRobustness:
    def test_invalid_inputs(self):
        assert resolve_title(None) == "Unknown title"
        assert resolve_title("") == "Unknown title"
        assert resolve_title("   ") == "Unknown title"
        assert resolve_title(123) == "Unknown title"

    def test_url_encoded_filename(self):
        url = "https://cdn.example.test/media/My%20Movie.2024.mp4?token=secret"
        assert resolve_title(url) == "My Movie.2024"

    @patch('urllib.request.urlopen')
    def test_amazon_network_failure(self, mock_urlopen):
        import urllib.error
        # Mock a timeout or DNS failure
        mock_urlopen.side_effect = urllib.error.URLError("Timeout")

        # When Amazon URL fails to fetch
        title = resolve_title("https://www.primevideo.com/detail/1234", provider="amazon")

        # It should fall back to "Amazon Video" (the fallback added in the refactor)
        assert title == "Amazon Video"

    @patch('urllib.request.urlopen')
    def test_amazon_no_title(self, mock_urlopen):
        # Mock HTML with no title tag
        mock_response = MagicMock()
        mock_response.read.return_value = b"<html><body>No title here</body></html>"
        mock_urlopen.return_value = mock_response

        title = resolve_title("https://www.primevideo.com/detail/5678", provider="amazon")
        assert title == "Amazon Video"


class TestParseIntentUrl:
    def test_parse_intent_url_amazon_watch(self):
        from castcast.metadata import parse_intent_url
        intent_url = (
            "intent://watch.amazon.com/watch?gti=amzn1.dv.gti.2a50e5b4-edfb-47c8-9b71-72d085008f16"
            "&time=0&territory=US&ref_=atv_dp_btf_el_prime_hd_tv_resume_t1ADAAAAAA0wr0&r=app"
            "#Intent;scheme=https;package=com.amazon.avod.thirdpartyclient;"
            "S.browser_fallback_url=https%3A%2F%2Fplay.google.com%2Fstore%2Fapps%2Fdetails%3Fid%3Dcom.amazon.avod.thirdpartyclient;end"
        )
        expected = (
            "https://watch.amazon.com/watch?gti=amzn1.dv.gti.2a50e5b4-edfb-47c8-9b71-72d085008f16"
            "&time=0&territory=US&ref_=atv_dp_btf_el_prime_hd_tv_resume_t1ADAAAAAA0wr0&r=app"
        )
        assert parse_intent_url(intent_url) == expected

    def test_parse_intent_url_custom_scheme(self):
        from castcast.metadata import parse_intent_url
        intent_url = "intent://my.host/path?arg=1#Intent;scheme=http;package=com.example;end"
        assert parse_intent_url(intent_url) == "http://my.host/path?arg=1"

    def test_parse_intent_url_default_scheme(self):
        from castcast.metadata import parse_intent_url
        intent_url = "intent://my.host/path?arg=1#Intent;package=com.example;end"
        assert parse_intent_url(intent_url) == "https://my.host/path?arg=1"

    def test_parse_intent_url_fallback(self):
        from castcast.metadata import parse_intent_url
        intent_url = "intent:#Intent;S.browser_fallback_url=https%3A%2F%2Fexample.com%2Fvideo;end"
        assert parse_intent_url(intent_url) == "https://example.com/video"

    def test_parse_intent_url_passthrough(self):
        from castcast.metadata import parse_intent_url
        assert parse_intent_url("https://example.com/video.mp4") == "https://example.com/video.mp4"
        assert parse_intent_url("/media/local.mp4") == "/media/local.mp4"
        assert parse_intent_url(None) is None


class TestResolveAmazonMediaInfo:
    @patch('urllib.request.urlopen')
    def test_resolve_catalog_id_to_canonical_gti_and_episode_title(self, mock_urlopen):
        from castcast.metadata import resolve_amazon_media_info
        import json, base64

        catalog_id = "0lmmoubsox8qg4wkzjxf5v87w6"
        expected_gti = "amzn1.dv.gti.6d5556d5-f739-4dcb-a3a1-9a68d8fcbcf6"
        b64_return = base64.b64encode(f"/detail/{catalog_id.upper()}?ref_=atv_dp_sign_suc".encode()).decode()

        mock_json = {
            "init": {
                "preparations": {
                    "body": {
                        "atf": {
                            "state": {
                                "pageTitleId": "amzn1.dv.gti.54bc782b-2be8-4072-bfeb-fe28e054d5ac",
                                "detail": {
                                    "headerDetail": {
                                        "amzn1.dv.gti.54bc782b-2be8-4072-bfeb-fe28e054d5ac": {
                                            "title": "Hazbin Hotel - Season 2"
                                        }
                                    }
                                }
                            }
                        },
                        "btf": {
                            "state": {
                                "detail": {
                                    "detail": {
                                        expected_gti: {
                                            "title": "It's A Deal",
                                            "episodeNumber": 4
                                        }
                                    }
                                },
                                "action": {
                                    "btf": {
                                        expected_gti: {
                                            "primaryActions": [{
                                                "payload": {
                                                    "expandingCard": {
                                                        "actions": [{
                                                            "payload": {
                                                                "subscription": {
                                                                    "signupLink": f"/signup?force_return_url=1&cGTI={expected_gti}&return_url={b64_return}"
                                                                }
                                                            }
                                                        }]
                                                    }
                                                }
                                            }]
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        mock_html = f"""
        <html>
        <head><title>Watch Hazbin Hotel Season 2 – Prime Video</title></head>
        <body>
        <script id="store" type="application/json">{json.dumps(mock_json)}</script>
        </body>
        </html>
        """.encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_html
        mock_urlopen.return_value = mock_resp

        url = f"https://www.primevideo.com/detail/{catalog_id}?autoplay=1&t=0&ref_=atv_dp_btf_el_prime_hd_tv_resume_t1adaaaaaa0wg0"
        res = resolve_amazon_media_info(url)
        assert res["gti"] == expected_gti
        assert res["title"] == "Hazbin Hotel - Season 2 - Ep 4: It's A Deal"
        assert res["episode"] == 4

    @patch('urllib.request.urlopen')
    def test_resolve_direct_gti_url(self, mock_urlopen):
        from castcast.metadata import resolve_amazon_media_info
        gti = "amzn1.dv.gti.2a50e5b4-edfb-47c8-9b71-72d085008f16"
        mock_html = b"<title>Watch Hazbin Hotel - Season 2 | Prime Video</title>"
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_html
        mock_urlopen.return_value = mock_resp

        url = f"https://watch.amazon.com/watch?gti={gti}"
        res = resolve_amazon_media_info(url)
        assert res["gti"] == gti
        assert res["title"] == "Hazbin Hotel - Season 2"

    @patch('urllib.request.urlopen')
    def test_resolve_url_with_referral_subpath(self, mock_urlopen):
        from castcast.metadata import resolve_amazon_media_info
        catalog_id = "0lmmoubsox8qg4wkzjxf5v87w6"
        mock_html = b"<title>Watch Hazbin Hotel - Season 2 | Prime Video</title>"
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_html
        mock_urlopen.return_value = mock_resp

        # Prime Video URL with /ref= path component
        url = f"https://www.primevideo.com/detail/{catalog_id}/ref=atv_dp_share_cu_r"
        res = resolve_amazon_media_info(url)
        assert res["title"] == "Hazbin Hotel - Season 2"
        # Verify requested URL used catalog_id, not 'ref'
        req_arg = mock_urlopen.call_args[0][0]
        req_url = req_arg.full_url if hasattr(req_arg, "full_url") else str(req_arg)
        assert catalog_id in req_url
        assert "/detail/ref" not in req_url

