"""Independent development-set certificate checks; does not import production math checks."""

from itertools import combinations


def subset_count(items, target):
    return sum(sum(choice) == target
               for size in range(len(items) + 1)
               for choice in combinations(items, size))


def verify():
    assert subset_count(range(1, 9), 9) == 7
    assert (40 * 40 + 40 + 41) == 41 * 41
    assert (2 * 2 - 4) == (2 - 2) * (2 + 2)
    assert 12 * 8 - 3 == 93
    assert all(sum(2 * k - 1 for k in range(1, n + 1)) == n * n
               for n in range(1, 201))
    # Parity-class certificate for the divisibility steps in the supplied proof.
    assert [r for r in range(2) if (r * r) % 2 == 0] == [0]
    assert [r for r in range(2) if (r * r) % 2 == 1] == [1]


if __name__ == "__main__":
    verify()
    print("development certificates verified")
