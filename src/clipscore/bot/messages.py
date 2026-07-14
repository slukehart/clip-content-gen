"""Discord message text. Pure formatting; honest-scoring literals are mandatory
(see the tests / plan Global Constraints)."""

CAVEAT = "estimated screening signal, not a payout prediction"
NOT_A_GATE = "relatively best in its niche — not a quality gate"


def format_alert(p: dict) -> str:
    pct = f"{p['percentile'] * 100:.0f}th pct" if p.get("percentile") is not None else "n/a"
    return (
        f"📈 **{p['title']}** ({p['niche']}) — {pct} in niche\n"
        f"{p['url']}\n"
        f"_{NOT_A_GATE}; {CAVEAT}._"
    )


def format_top(rows: list[dict], niche) -> str:
    scope = f"niche '{niche}'" if niche else "all niches"
    lines = [f"**Top campaigns — {scope}** (_{CAVEAT}_)", ""]
    if not rows:
        lines.append("(no scored campaigns)")
        return "\n".join(lines)
    for i, r in enumerate(rows, 1):
        pct = r["cvs_niche_percentile"]
        pcts = f"{pct * 100:.0f}%" if pct is not None else "-"
        lines.append(f"{i}. {r['niche']:<14} {(r['title'] or '')[:32]:<32} pctile={pcts}")
    return "\n".join(lines)


def format_summary(top_per_niche: list[dict], movers: list[dict], now_iso: str) -> str:
    lines = [f"**Daily screening summary** — {now_iso} (_{CAVEAT}_)", "", "__Top per niche__"]
    for r in top_per_niche:
        pct = r.get("cvs_niche_percentile")
        pcts = f"{pct * 100:.0f}%" if pct is not None else "-"
        lines.append(f"• {r['niche']:<14} {(r.get('title') or '')[:32]:<32} pctile={pcts}")
    lines += ["", "__Biggest movers (change in relative niche standing)__"]
    if not movers:
        lines.append("(none)")
    for m in movers:
        arrow = "▲" if m["delta"] >= 0 else "▼"
        lines.append(f"{arrow} {(m['title'] or '')[:32]:<32} {m['niche']:<14} "
                     f"{m['past'] * 100:.0f}% → {m['current'] * 100:.0f}% "
                     f"({m['delta'] * 100:+.0f} pts)")
    return "\n".join(lines)
