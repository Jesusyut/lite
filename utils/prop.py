def american_to_prob(american: int | float | None) -> float | None:
    if american is None: return None
    a = float(american)
    if a > 0:  return 100.0 / (a + 100.0)
    else:      return (-a) / ((-a) + 100.0)
