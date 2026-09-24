"""Two independent counts for the diagnostic graph; no model or pipeline import."""

from itertools import combinations


VERTICES = tuple(range(10))
EDGE_DIFFERENCES = {1, 3, 7, 9}


def adjacent(a: int, b: int) -> bool:
    return (a - b) % 10 in EDGE_DIFFERENCES


def direct_count() -> int:
    return sum(
        all(not adjacent(a, b) for a, b in combinations(subset, 2))
        for subset in combinations(VERTICES, 4)
    )


def mask_count() -> int:
    neighbor_masks = tuple(
        sum(1 << j for j in VERTICES if adjacent(i, j)) for i in VERTICES
    )

    def visit(next_vertex: int, chosen_mask: int, chosen_count: int) -> int:
        if chosen_count == 4:
            return 1
        if next_vertex == 10 or chosen_count + 10 - next_vertex < 4:
            return 0
        skip = visit(next_vertex + 1, chosen_mask, chosen_count)
        if neighbor_masks[next_vertex] & chosen_mask:
            return skip
        return skip + visit(
            next_vertex + 1, chosen_mask | (1 << next_vertex), chosen_count + 1
        )

    return visit(0, 0, 0)


if __name__ == "__main__":
    print({"direct": direct_count(), "mask": mask_count()})
