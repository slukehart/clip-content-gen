from clipscore.factory.acquire.campaign_provided import CampaignProvidedAcquirer, _normalize_share_url


def test_drive_file_link_normalized_to_direct_download():
    u = _normalize_share_url("https://drive.google.com/file/d/ABC123/view?usp=sharing")
    assert u == "https://drive.google.com/uc?export=download&id=ABC123"


def test_dropbox_link_forced_to_direct():
    assert _normalize_share_url("https://www.dropbox.com/s/x/v.mp4?dl=0").endswith("dl=1")


def test_drive_folder_link_is_manual():
    a = CampaignProvidedAcquirer()
    r = a.acquire("https://drive.google.com/drive/folders/XYZ", "/tmp/ignored")
    assert r.status == "manual" and r.error == "folder_or_unsupported_share_link"
    assert a.requires_authorization is False
