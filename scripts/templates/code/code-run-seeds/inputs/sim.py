"""Counts how many of 1,000,000 pseudo-random points fall inside the quarter circle."""
import sys


def run(seed, points=1_000_000):
    x, inside = seed, 0
    for _ in range(points):
        x = (x * 1103515245 + 12345) % 2147483648
        a = x / 2147483648
        x = (x * 1103515245 + 12345) % 2147483648
        b = x / 2147483648
        inside += a * a + b * b < 1
    return inside


if __name__ == "__main__":
    print("inside=%d" % run(int(sys.argv[1])))
