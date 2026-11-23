from roman import to_roman, from_roman

assert to_roman(4) == "IV" and to_roman(1994) == "MCMXCIV"
for n in range(1, 4000):
    assert from_roman(to_roman(n)) == n, f"round trip fails for {n}"
print("OK")
