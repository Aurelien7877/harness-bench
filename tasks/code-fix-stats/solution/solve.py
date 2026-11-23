from pathlib import Path
Path('stats_utils.py').write_text('''def chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def percent(part, total):
    return round(part / total * 100, 1) if total else 0.0
''')
