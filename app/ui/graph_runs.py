"""The run fold: a long series is drawn as each run's min and max, the runs at fixed sample positions so they stay put
while the view pans; no Kivy, so it is tested as plain arithmetic."""
import math
from collections.abc import Callable

# A run's min and max are 2 of MinMax's 3 points per stroke width at its elbow, so a run spans 2/3 of the stroke.
RUN_STROKES = 2 / 3
MIN_RUN = 4  # samples: a shorter run saves too little to be worth folding


def extremes(values: list[float], start: int, stop: int) -> tuple[int, int]:
    """Indices of values[start:stop]'s min and max, in sample order."""
    run = values[start:stop]
    lo, hi = start + run.index(min(run)), start + run.index(max(run))
    return (lo, hi) if lo <= hi else (hi, lo)


class RunExtremes:
    """One series' min and max per run of `size` samples at fixed positions, kept as data arrives (as Audacity's)."""

    __slots__ = ("size", "base", "idx")

    def __init__(self, size: int) -> None:
        self.size = size
        self.base = 0  # the absolute run number of idx[0:2]
        self.idx: list[int] = []  # two absolute sample indices per run: its min and max in sample order

    def runs(self, values: list[float], v0: int, first: int, last: int) -> list[int]:
        """Absolute indices for runs first..last-1, which lie inside values (values[0] is absolute sample v0)."""
        have = self.base + len(self.idx) // 2
        if last < self.base or first > have:  # nothing kept touches the window: start over at it
            self.base, self.idx, have = first, [], first
        if first < self.base:  # panned back: only the runs before what is kept
            self.idx[:0] = self._scan(values, v0, first, self.base)
            self.base = first
        if have < last:
            self.idx.extend(self._scan(values, v0, have, last))
        out = self.idx[2 * (first - self.base):2 * (last - self.base)]
        if first - self.base > 2 * (last - first):  # far behind the window, as runs the buffer has dropped are
            del self.idx[:2 * (first - self.base)]
            self.base = first
        return out

    def _scan(self, values: list[float], v0: int, first: int, last: int) -> list[int]:
        size = self.size
        return [v0 + i for r in range(first, last) for i in extremes(values, r * size - v0, (r + 1) * size - v0)]


def run_indices(values: list[float], per_px: float, stroke: float, v0_of: Callable[[], int],
                kept_for: Callable[[int], RunExtremes]) -> range | list[int]:
    """Indices into values to draw: every one, or each run's min and max and the series' two ends. A pixel holds
    per_px samples and the line is `stroke` pixels thick; values[0] is absolute sample v0_of(), asked only when the
    series folds, and kept_for(size) gives the series' kept runs."""
    n = len(values)
    longest = per_px * stroke * RUN_STROKES  # samples in a run spanning RUN_STROKES of the stroke
    if n < 3 or longest < MIN_RUN:
        return range(n)
    size = 1 << int(math.log2(longest))  # a power of two: the runs stay put until the zoom doubles
    v0 = v0_of()
    first, last = -(-v0 // size), (v0 + n) // size
    if last <= first:
        return range(n)
    out = [0]
    if first * size > v0:
        out.extend(extremes(values, 0, first * size - v0))
    out.extend(i - v0 for i in kept_for(size).runs(values, v0, first, last))
    if last * size - v0 < n:
        out.extend(extremes(values, last * size - v0, n))
    out.append(n - 1)
    return [i for j, i in enumerate(out) if j == 0 or i != out[j - 1]]
