from pathlib import Path
Path('roman.py').write_text('''PAIRS = [(1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]


def to_roman(n):
    out = ''
    for value, symbol in PAIRS:
        while n >= value:
            out += symbol
            n -= value
    return out


def from_roman(s):
    total = 0
    for value, symbol in PAIRS:
        while s.startswith(symbol):
            total += value
            s = s[len(symbol):]
    return total
''')
