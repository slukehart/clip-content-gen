from clipscore.factory.acquire import storage


def test_stem_key_is_stable_and_source_typed():
    k1 = storage.stem_key("campaign_provided", "https://drive.google.com/uc?id=A")
    k2 = storage.stem_key("campaign_provided", "https://drive.google.com/uc?id=A")
    assert k1 == k2 and k1.startswith("campaign_provided/")
    assert k1 != storage.stem_key("youtube", "https://drive.google.com/uc?id=A")


def test_path_for_joins_media_dir_stem_ext():
    assert storage.path_for("media/", "youtube/abc123", ".mp4") == "media/youtube/abc123.mp4"


def test_find_existing_returns_nonempty_match(tmp_path):
    (tmp_path / "campaign_provided").mkdir()
    stem = storage.stem_key("campaign_provided", "ref-1")
    f = tmp_path / f"{stem}.mp4"
    f.write_bytes(b"x" * 10)
    assert storage.find_existing(str(tmp_path), "campaign_provided", "ref-1") == str(f)
    assert storage.find_existing(str(tmp_path), "campaign_provided", "ref-missing") is None


def test_dir_usage_bytes_sums_files(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.bin").write_bytes(b"x" * 100)
    assert storage.dir_usage_bytes(str(tmp_path)) == 100
    assert storage.dir_usage_bytes(str(tmp_path / "nope")) == 0
