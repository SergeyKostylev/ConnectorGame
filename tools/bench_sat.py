"""
Benchmark of the sat generator (app/services/DataMapGeneratorSat.py).
Writes nothing to levels/ — only prints a table.

For every size x seed it generates one level and reports: time, candidates,
witnesses, actual battery/lamp %, single-lamp networks, short networks, lamps
next to a battery, straight share, longest straight run. Every level is
re-checked with the orphan checker (must say 'ok').

Usage:
    python3 tools/bench_sat.py                              # default sizes, 3 seeds
    python3 tools/bench_sat.py --sizes 11x12 15x15 --batteries 8 --lamps 25
    python3 tools/bench_sat.py --nogood legacy              # A/B the nogood
    python3 tools/bench_sat.py --no-minimize                # witnesses not minimised
"""
import argparse
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app.services.DataMapGeneratorSat as sat

_DELTA = sat._DELTA


def level_metrics(data_map):
    """Measured from the finished level, independent of the model's variables."""
    rows, cols = len(data_map), len(data_map[0])
    n = rows * cols
    conns = [sat_conns(data_map[v // cols][v % cols]) for v in range(n)]
    types = [data_map[v // cols][v % cols]['type'] for v in range(n)]
    names = [data_map[v // cols][v % cols]['name'] for v in range(n)]

    def nbrs(v):
        i, j = divmod(v, cols)
        for d, (di, dj) in enumerate(_DELTA):
            ni, nj = i + di, j + dj
            if conns[v][d] and 0 <= ni < rows and 0 <= nj < cols:
                yield ni * cols + nj

    bats = [v for v in range(n) if types[v] == 'battery']
    lamps = sum(t == 'target' for t in types)
    sizes, lamp_counts, near, direct = [], [], 0, 0
    for b in bats:
        dist, stack = {b: 0}, [b]
        while stack:
            v = stack.pop()
            for u in nbrs(v):
                if u not in dist:
                    dist[u] = dist[v] + 1
                    stack.append(u)
        sizes.append(len(dist))
        net_lamps = [v for v in dist if types[v] == 'target']
        lamp_counts.append(len(net_lamps))
        near += sum(dist[v] == 2 for v in net_lamps)
        direct += sum(dist[v] == 1 for v in net_lamps)
    avg = n / max(1, len(bats))
    pipes = [v for v in range(n) if types[v] == 'pipeline']
    straights = sum(names[v] == 'l' for v in pipes)

    longest = 0                      # longest run of straights along their axis
    for v in pipes:
        if names[v] != 'l':
            continue
        i, j = divmod(v, cols)
        horizontal = conns[v][1]
        di, dj = (0, 1) if horizontal else (1, 0)
        pi, pj = i - di, j - dj      # count each run from its first tile
        if 0 <= pi < rows and 0 <= pj < cols and names[pi * cols + pj] == 'l' \
                and conns[pi * cols + pj] == conns[v]:
            continue
        k, ci, cj = 0, i, j
        while 0 <= ci < rows and 0 <= cj < cols and names[ci * cols + cj] == 'l' \
                and conns[ci * cols + cj] == conns[v]:
            k, ci, cj = k + 1, ci + di, cj + dj
        longest = max(longest, k)

    return {
        'bat_pct': 100 * len(bats) / n,
        'lamp_pct': 100 * lamps / n,
        'single': sum(c == 1 for c in lamp_counts),
        'short': sum(s < sat.SHORT_NET_RATIO * avg for s in sizes),
        'near': near,
        'direct': direct,
        'nets': len(bats),
        'lamps': lamps,
        'straight_pct': 100 * straights / max(1, len(pipes)),
        'longest_straight': longest,
    }


def sat_conns(cell):
    from app.models.MatrixFrame import MatrixFrame
    mf = MatrixFrame(cell['name'], cell['rotation'], cell['type'])
    return tuple(mf.has_connector(d) for d in sat._DIRS)


def recheck(data_map):
    w = sat.find_witnesses(data_map, 60, sat.DEFAULT_WORKERS, max_witnesses=1)
    return 'ok' if w == [] else ('ORPHANS' if w else 'timeout')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sizes', nargs='*', default=['9x5', '11x12', '15x15'])
    ap.add_argument('--batteries', type=float, default=5, help='batteries %%')
    ap.add_argument('--lamps', type=float, default=20, help='lamps %%')
    ap.add_argument('--seeds', type=int, default=3)
    ap.add_argument('--time-limit', type=float, default=sat.DEFAULT_TIME_LIMIT)
    ap.add_argument('--nogood', choices=['local', 'legacy'], default=sat.NOGOOD_MODE)
    ap.add_argument('--no-minimize', action='store_true')
    args = ap.parse_args()
    sat.NOGOOD_MODE = args.nogood
    sat.MINIMIZE_WITNESS = not args.no_minimize

    print(f"batteries {args.batteries}%, lamps {args.lamps}%, nogood={args.nogood}, "
          f"minimize={'no' if args.no_minimize else 'yes'}, limit {args.time_limit:g}s\n")
    hdr = (f"{'size':>6} {'seed':>4} {'result':>8} {'time':>6} {'cand':>5} {'wit':>4} "
           f"{'bat%':>5} {'lamp%':>6} {'1-lamp':>7} {'short':>6} {'near':>5} "
           f"{'strt%':>6} {'run':>4} {'check':>7}")
    print(hdr)
    print('-' * len(hdr))
    for size in args.sizes:
        rows, cols = map(int, size.lower().split('x'))
        times = []
        for seed in range(args.seeds):
            gen = sat.GeneratorSat(time_limit=args.time_limit, seed=seed, log=lambda m: None)
            t0 = time.time()
            try:
                dm = gen.generate(rows, cols, args.batteries, args.lamps)
            except (RuntimeError, ValueError) as e:
                st = gen.stats
                print(f"{size:>6} {seed:>4} {'FAIL':>8} {time.time() - t0:6.1f} "
                      f"{st.get('candidates', 0):>5} {st.get('witnesses', 0):>4}  {e}")
                continue
            took = time.time() - t0
            times.append(took)
            mt, st = level_metrics(dm), gen.stats
            print(f"{size:>6} {seed:>4} {'ok':>8} {took:6.1f} {st['candidates']:>5} "
                  f"{st['witnesses']:>4} {mt['bat_pct']:5.1f} {mt['lamp_pct']:6.1f} "
                  f"{mt['single']:>3}/{mt['nets']:<3} {mt['short']:>6} "
                  f"{mt['near']:>2}/{mt['lamps']:<2} {mt['straight_pct']:6.0f} "
                  f"{mt['longest_straight']:>4} {recheck(dm):>7}", flush=True)
            if mt['direct']:
                print(f"       !! {mt['direct']} lamp(s) wired straight to a battery")
        if times:
            print(f"{size:>6} median {statistics.median(times):.1f}s over {len(times)} levels\n")


if __name__ == '__main__':
    main()
