from stats_utils import chunks, median, percent

assert chunks([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
assert chunks([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
assert median([3, 1, 2]) == 2
assert median([4, 1, 3, 2]) == 2.5
assert percent(1, 4) == 25.0
assert percent(2, 3) == 66.7
assert percent(5, 0) == 0.0
print("OK")
