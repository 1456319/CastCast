from castcast.amazon_drm import _build_vod_playback_resources_payload


def test_vod_playback_resources_uses_keyed_capability_maps():
    payload = _build_vod_playback_resources_payload("envelope", "title")

    dash = payload["vodPlaylistedPlaybackUrlsRequest"]["device"]["streamingTechnologies"]["DASH"]

    assert dash["codecs"] == {"H265": {}, "H264": {}}
    assert dash["dynamicRangeFormats"] == {"HDR10": {}, "SDR": {}}
    assert dash["bitrateAdaptations"] == {"CVBR": {}}
    assert payload["vodPlaylistedPlaybackUrlsRequest"]["device"]["supportedStreamingTechnologies"] == {"DASH": {}}


def test_vod_playback_resources_keeps_title_and_envelope():
    payload = _build_vod_playback_resources_payload("envelope", "title")

    settings = payload["vodPlaylistedPlaybackUrlsRequest"]["playbackSettingsRequest"]
    globals_ = payload["globalParameters"]

    assert settings["titleId"] == "title"
    assert globals_["playbackEnvelope"] == "envelope"
    assert globals_["deviceCapabilityFamily"] == "LivingRoomPlayer"
