"""Within-niche rank as an empirical CDF (IMPLEMENTATION_PLAN.md:167). The primary
user-facing signal. Population = the campaign's niche's valid scored campaigns."""


def empirical_cdf(value: float, population: list[float]) -> float:
    n = len(population)
    if n == 0:
        raise ValueError("empty population")
    return sum(1 for x in population if x <= value) / n
