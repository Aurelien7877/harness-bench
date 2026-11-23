import os, sys
sys.path.insert(0, os.getcwd())
import json
from pathlib import Path
checks, errors = {}, {}
try:
    from stats_utils import chunks, median, percent
    cases = {
        'chunks_exact': lambda: chunks(list(range(6)), 3) == [[0, 1, 2], [3, 4, 5]],
        'chunks_remainder': lambda: chunks(list(range(7)), 3) == [[0, 1, 2], [3, 4, 5], [6]],
        'chunks_short': lambda: chunks([1], 5) == [[1]] and chunks([], 3) == [],
        'median_odd': lambda: median([9, 1, 5, 7, 3]) == 5,
        'median_even': lambda: median([10, 2, 8, 4]) == 6 and median([1, 2]) == 1.5,
        'median_single': lambda: median([7]) == 7,
        'percent_round': lambda: percent(1, 3) == 33.3 and percent(2, 3) == 66.7 and percent(1, 6) == 16.7,
        'percent_zero': lambda: percent(0, 0) == 0.0 and percent(3, 0) == 0.0,
        'percent_exact': lambda: percent(1, 8) == 12.5 and percent(7, 7) == 100.0,
    }
    for name, case in cases.items():
        try:
            checks[name] = bool(case())
        except Exception as error:
            checks[name] = False
            errors[name] = type(error).__name__ + ': ' + str(error)
    import subprocess, sys
    checks['visible_test'] = subprocess.run([sys.executable, 'test_stats_utils.py'], capture_output=True, timeout=10).returncode == 0
except Exception as error:
    checks['importable'] = False
    errors['import'] = type(error).__name__ + ': ' + str(error)
target = Path('/logs/verifier') if Path('/logs/verifier').is_dir() else Path('.')
(target / 'criteria.json').write_text(json.dumps({'checks': checks, 'errors': errors}, indent=2))
assert checks and all(checks.values()), json.dumps({'checks': checks, 'errors': errors})
