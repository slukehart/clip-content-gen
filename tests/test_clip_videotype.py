import pytest

from clipscore.factory.clip.videotype import detect_video_type


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=NgUNjjV_AkY", (2, None)),
    ("https://youtu.be/NgUNjjV_AkY", (2, None)),
    ("https://m.youtube.com/watch?v=abc", (2, None)),
    ("https://drive.google.com/file/d/1AbC/view?usp=sharing", (3, None)),
    ("https://vimeo.com/123456789", (4, None)),
    ("https://www.twitch.tv/videos/123456789", (9, None)),
    ("https://cdn.example.com/path/clip.mp4", (1, "mp4")),
    ("https://cdn.example.com/path/clip.MOV?token=x", (1, "mov")),
    ("https://cdn.example.com/a.avi", (1, "avi")),
    ("https://cdn.example.com/a.3gp", (1, "3gp")),
])
def test_detects_supported(url, expected):
    assert detect_video_type(url) == expected


@pytest.mark.parametrize("url", [
    "https://drive.google.com/drive/folders/1AbC",   # folder, not a file
    "https://docs.google.com/document/d/1AbC/edit",  # doc
    "https://example.com/page.html",                 # not a media file
    "https://example.com/watch",                     # no extension, unknown host
    "https://example.com/clip.txt",                  # unsupported extension
    "",
    "not a url",
])
def test_rejects_unsupported(url):
    assert detect_video_type(url) is None


def test_config_has_usd_per_credit():
    from clipscore.config import Settings
    assert Settings().vizard_usd_per_credit == 0.0
