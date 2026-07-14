"""Pure scoring primitives (no DB, no I/O). Verbatim from IMPLEMENTATION_PLAN.md
lines 185-219. Provenance: net_cpm/sat_factor are OBSERVED-driven; the p_* factors
and e_views are GUESSED constants (see engine.py)."""


def net_cpm(cpm_usd: float, fee_pct: float) -> float:
    return cpm_usd * (1 - fee_pct)


def raw_earnings(net_cpm_val: float, e_views: float) -> float:
    return net_cpm_val * (e_views / 1000)


def capped_earnings(raw: float, cap_per_post_usd, cap_provenance: str, default_cap: float) -> float:
    # unknown cap != uncapped: absent (or observed-but-missing) -> conservative default
    if cap_provenance == "observed" and cap_per_post_usd is not None:
        return min(raw, cap_per_post_usd)
    return min(raw, default_cap)


def sat_factor(budget_remaining_now, active_clippers) -> float:
    if budget_remaining_now is None or active_clippers is None:
        return 0.8
    saturation = budget_remaining_now / max(active_clippers, 1)
    return min(1.0, saturation / 200)


def ev_per_clip(capped: float, p_threshold: float, p_approval: float,
                p_payout: float, budget_health: float, sat: float) -> float:
    return capped * p_threshold * p_approval * p_payout * budget_health * sat


def cvs_raw(ev: float, hours_per_clip: float) -> float:
    return ev / hours_per_clip
