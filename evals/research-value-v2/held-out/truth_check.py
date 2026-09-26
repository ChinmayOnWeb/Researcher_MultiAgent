"""Independent held-out arithmetic checks; never imported by production code."""

from itertools import combinations


def subset_count(items, target):
    return sum(sum(choice) == target
               for size in range(len(items) + 1)
               for choice in combinations(items, size))


def verify():
    assert subset_count(range(1, 10), 10) == 9
    assert all(sum(range(1, n + 1)) == n * (n + 1) // 2
               for n in range(1, 201))
    assert 16 * 16 + 16 + 17 == 17 * 17
    assert (3 - 3) * (3 + 3) == 3 * 3 - 9
    assert min(29 // 3, 74 // 8) == 9
    assert 74 - 9 * 8 == 2


if __name__ == "__main__":
    verify()
    print("held-out certificates verified")
