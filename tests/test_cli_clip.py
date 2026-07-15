from clipscore.cli import build_parser

def test_clip_subcommand_parses():
    args = build_parser().parse_args(["clip", "c1", "--source-type", "url", "--source-ref", "http://x/v.mp4"])
    assert args.cmd == "clip" and args.campaign_id == "c1"
    assert args.source_type == "url" and args.source_ref == "http://x/v.mp4"
