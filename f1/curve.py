"""Reconstruct a circuit outline from F1 position samples.

Why derived rather than downloaded
----------------------------------
Formula 1 publishes no circuit vector data, and the coordinates on Position.z
are integers in an unpublished per-circuit local frame -- not latitude and
longitude. The two free alternatives were both tried and both fail:

* OpenStreetMap raceway relations do contain the track, but a relation also
  carries the pit lane, access roads and the paddock. For Baku the recovered
  loop came out at 7.8 km against a 6.0 km lap, and it could not be told apart
  from the real lap reliably. It is also ODbL, which would put share-alike
  obligations on the plugin.
* The public static archive keeps only ~3 position samples per session. Across
  every Baku session since 2018 that is 443 distinct points, unevenly spread,
  which is not enough to order them into a lap.

A live session, by contrast, produces thousands of well-distributed samples,
which is exactly what this module wants. So the outline is learned from the
same telemetry the car markers are drawn from: one frame, no transform, so a
marker cannot drift off its own track. The runtime service refreshes it while a
session runs and caches it per circuit, and a circuit is drawn only once a real
outline for it exists -- an unlearned circuit says so rather than showing a
guess.

The pipeline:

1. density filter -- merge near-duplicate samples into cell centroids;
2. connected components -- keep the largest, discarding sentinel coordinates
   the feed emits for cars that are no longer on the circuit;
3. tour -- greedy nearest neighbour then 2-opt, which recovers the lap because
   the shortest tour through points sampled from a closed curve is the curve;
4. resample, smooth, simplify.

What it is not: a survey. The result traces the corridor the cars drive, so
kerbs and run-off are not represented. That is the right trade for a live
position map, and it is documented rather than implied.
"""

from __future__ import annotations

import math

# A lap longer than this is a tour that got tangled, not a circuit. The longest
# current lap is Austin at 5.513 km, so the bound leaves headroom while still
# catching a failure.
MAX_LAP_M = 8000.0
MIN_LAP_M = 1200.0
MIN_POINTS = 12


def density_filter(points, cell: float = 6.0, min_count: int = 1):
    """Merge near-duplicate samples into cell centroids.

    The centroid is an average of observations, never a new position, so this
    does not invent geometry that was not measured.
    """
    if not points:
        return []
    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for p in points:
        buckets.setdefault((int(p[0] // cell), int(p[1] // cell)), []).append((float(p[0]), float(p[1])))
    out = []
    for cell_pts in buckets.values():
        if len(cell_pts) < min_count:
            continue
        out.append(
            (
                sum(p[0] for p in cell_pts) / len(cell_pts),
                sum(p[1] for p in cell_pts) / len(cell_pts),
            )
        )
    return out


def largest_component(points, radius: float = 90.0):
    """Keep the biggest connected blob; everything else is feed debris.

    Sentinels for cars that have left the circuit sit far from the track, and
    with dense live data they form small separate components rather than
    isolated points, so connectivity is a more reliable test than distance.
    """
    n = len(points)
    if n < 3:
        return list(points)
    comp = [-1] * n
    best = (0, -1)
    cid = 0
    for start in range(n):
        if comp[start] != -1:
            continue
        stack = [start]
        comp[start] = cid
        count = 0
        while stack:
            i = stack.pop()
            count += 1
            for j in range(n):
                if comp[j] == -1 and j != i and math.dist(points[i], points[j]) <= radius:
                    comp[j] = cid
                    stack.append(j)
        if count > best[0]:
            best = (count, cid)
        cid += 1
    return [points[i] for i in range(n) if comp[i] == best[1]]


def greedy_tour(points, start: int = 0):
    """Nearest-neighbour tour. Cheap; 2-opt repairs its mistakes."""
    n = len(points)
    unvisited = set(range(n)) - {start}
    tour = [start]
    cur = start
    while unvisited:
        nxt = min(unvisited, key=lambda j: math.dist(points[cur], points[j]))
        unvisited.discard(nxt)
        tour.append(nxt)
        cur = nxt
    return tour


def two_opt(tour, points, max_passes: int = 300):
    """Untangle a tour by reversing crossed segments.

    Reversing tour[i..j] swaps the edges (i-1,i) and (j,j+1) for (i-1,j) and
    (i,j+1). Reversing a crossing always shortens a tour, so repeated
    application converges on the non-self-intersecting tour, which for points
    sampled from a closed track is the lap.

    The search is exhaustive -- a few hundred points makes each pass ~n^2/2
    constant-time checks, and first-improvement restarts straight away.
    """
    n = len(tour)
    if n < 5:
        return list(tour)
    # Cyclic view: one extra slot repeats the first node so the edge that wraps
    # past the end of the lap needs no special case.
    tour = list(tour) + [tour[0]]
    pts = points

    def edge(a, b):
        return math.dist(pts[a], pts[b])

    for _ in range(max_passes):
        improved = False
        for i in range(1, n - 1):
            ai, bi = tour[i - 1], tour[i]
            base = edge(ai, bi)
            for j in range(i + 2, n):
                aj, bj = tour[j], tour[j + 1]
                if base + edge(aj, bj) - edge(ai, aj) - edge(bi, bj) > 1e-9:
                    tour[i : j + 1] = tour[i : j + 1][::-1]
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return tour[:n]


def resample(points, step: float) -> list[tuple[float, float]]:
    """Even arc-length resampling, so smoothing is stable."""
    if len(points) < 2:
        return list(points)
    closed = points[0] == points[-1]
    src = list(points[:-1]) if closed else list(points)
    out = [tuple(src[0])]
    carry = 0.0
    last = len(src) if closed else len(src) - 1
    for i in range(last):
        a = src[i]
        b = src[(i + 1) % len(src)]
        seg = math.dist(a, b)
        if seg <= 1e-9:
            continue
        t = step - carry
        while t <= seg:
            f = t / seg
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            t += step
        carry = (carry + seg) % step
    return out


def smooth(points, window: int = 4, passes: int = 3):
    """Moving average along the path. Endpoints stay pinned so the line never
    drifts to somewhere no car was observed."""
    n = len(points)
    if n < 3:
        return list(points)
    window = max(1, min(window, (n - 1) // 2))
    out = list(points)
    for _ in range(passes):
        nxt = list(out)
        for i in range(1, n - 1):
            lo, hi = max(0, i - window), min(n, i + window + 1)
            cnt = hi - lo
            nxt[i] = (
                sum(out[j][0] for j in range(lo, hi)) / cnt,
                sum(out[j][1] for j in range(lo, hi)) / cnt,
            )
        out = nxt
    return out


def rdp(points, eps: float):
    """Ramer-Douglas-Peucker simplification."""
    if len(points) < 3:
        return list(points)
    ax, ay = points[0]
    bx, by = points[-1]
    dx, dy = bx - ax, by - ay
    norm = math.hypot(dx, dy)
    best_i, best_d = 0, -1.0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if norm == 0:
            d = math.hypot(px - ax, py - ay)
        else:
            d = abs(dy * px - dx * py + bx * ay - by * ax) / norm
        if d > best_d:
            best_i, best_d = i, d
    if best_d <= eps:
        return [points[0], points[-1]]
    return rdp(points[: best_i + 1], eps)[:-1] + rdp(points[best_i:], eps)


def path_length(points) -> float:
    return sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def build_outline(
    samples,
    *,
    radius: float = 90.0,
    step: float = 8.0,
    smooth_window: int = 4,
    smooth_passes: int = 3,
    eps: float = 5.0,
    max_points: int = 1200,
):
    """Scattered position samples -> an ordered, simplified lap.

    Returns None when the input is too sparse or the result fails a sanity
    check, so a half-learned circuit is never drawn as if it were complete.
    """
    pts = density_filter(samples, cell=6.0, min_count=1)
    if len(pts) > max_points:
        # Thin deterministically: keep a spread, not a prefix, so the shape is
        # preserved when a long session has been accumulating.
        step_n = len(pts) / max_points
        pts = [pts[int(i * step_n)] for i in range(max_points)]
    pts = largest_component(pts, radius=radius)
    if len(pts) < MIN_POINTS:
        return None

    tour = two_opt(greedy_tour(pts), pts)
    path = [pts[i] for i in tour]
    path.append(path[0])

    raw_length = path_length(path)
    if not (MIN_LAP_M * 0.5 <= raw_length <= MAX_LAP_M * 1.6):
        return None

    path = resample(path, step)
    path = smooth(path, window=smooth_window, passes=smooth_passes)
    path = rdp(path, eps)
    if len(path) < MIN_POINTS:
        return None
    if math.dist(path[0], path[-1]) < step * 1.5:
        path = path + [path[0]]

    length = path_length(path)
    if not (MIN_LAP_M <= length <= MAX_LAP_M):
        return None
    return path
