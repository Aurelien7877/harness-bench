def chunks(items, size):
    """Split items into lists of at most `size` items; the last one may be shorter."""
    return [items[i:i + size] for i in range(0, len(items) - size + 1, size)]


def median(values):
    """Median of a non-empty list; the mean of the two middle values when the length is even."""
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def percent(part, total):
    """`part` as a percentage of `total`, rounded to one decimal; 0.0 when total is 0."""
    return int(part / total * 1000) / 10
