import pytest
import base64
from unittest.mock import patch, MagicMock
from castcast.metadata import resolve_title, _clean_title

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
