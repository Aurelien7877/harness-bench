import os, sys
sys.path.insert(0, os.getcwd())
import json
from pathlib import Path
checks, errors = {}, {}
known = {1: 'I', 4: 'IV', 9: 'IX', 14: 'XIV', 40: 'XL', 90: 'XC', 400: 'CD', 900: 'CM', 1994: 'MCMXCIV', 2024: 'MMXXIV', 3888: 'MMMDCCCLXXXVIII', 3999: 'MMMCMXCIX'}
try:
    from roman import to_roman, from_roman
    def known_values():
        return all(to_roman(n) == s for n, s in known.items())
    def reverse_values():
        return all(from_roman(s) == n for n, s in known.items())
    def round_trip():
        return all(from_roman(to_roman(n)) == n for n in range(1, 4000))
    def distinct():
        return len({to_roman(n) for n in range(1, 4000)}) == 3999
    for name, case in {'known_values': known_values, 'reverse_values': reverse_values, 'round_trip': round_trip, 'distinct': distinct}.items():
        try:
            checks[name] = bool(case())
        except Exception as error:
            checks[name] = False
            errors[name] = type(error).__name__ + ': ' + str(error)
except Exception as error:
    checks['importable'] = False
    errors['import'] = type(error).__name__ + ': ' + str(error)
target = Path('/logs/verifier') if Path('/logs/verifier').is_dir() else Path('.')
(target / 'criteria.json').write_text(json.dumps({'checks': checks, 'errors': errors}, indent=2))
assert checks and all(checks.values()), json.dumps({'checks': checks, 'errors': errors})
