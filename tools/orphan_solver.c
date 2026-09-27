/*
 * orphan_solver — the per-tile search of tools/orphan_checker.py (unpowered
 * mode). Backtracking over cell rotations with conflict-directed
 * backjumping: a dead end jumps straight back to the deepest cell that
 * caused it, skipping unrelated cells. It visits a subset of the plain
 * backtracking tree in the same order, so results are the same, with fewer
 * steps (see ok() and backtrack()).
 *
 * Build:  make build-solver      (cc -O2 -o tools/orphan_solver tools/orphan_solver.c)
 *
 * Protocol (text, one long-lived process per level check; driven by
 * CSolver in orphan_checker.py):
 *
 *   in:   Q <rows> <cols> <candidate> <budget> <found_budget> <found>
 *         then rows*cols cells, row-major:  <type> <ndom> <mask> ... <mask>
 *           type: 0 pipeline/wall, 1 battery, 2 target
 *           mask: open sides, bit 0 up, 1 right, 2 down, 3 left
 *         budget:       steps allowed per tile while no orphan was found yet
 *         found_budget: steps allowed per tile once an orphan was found (the
 *                       level is failed; it's only worth continuing while
 *                       tiles are cheap)
 *         found:        1 if the level check already found an orphan (the
 *                       checker runs several solvers in parallel and tells
 *                       each one), 0 otherwise
 *         All come with every query, so changing them in Python needs no rebuild.
 *
 *   out:  P <steps>                     progress, every 65536 steps
 *         R ok <steps>                  no win state leaves the candidate unpowered
 *         R timeout <steps>             budget exceeded, no orphan found yet
 *         R stop <steps>                found_budget exceeded after an orphan was found
 *         R unused <steps> <mask>*n     a win state with the candidate unpowered
 *
 * The process exits on end of input, or when its parent dies.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

enum { T_PIPE = 0, T_BATT = 1, T_TARG = 2 };

static const int OPP[4] = {2, 3, 0, 1};
static const int DR[4]  = {-1, 0, 1, 0};
static const int DC[4]  = {0, 1, 0, -1};

static int n, rows, cols, cand;
static long long budget, found_budget, limit, steps;
static int found_any;            /* an orphan was found: by this process or (per query) the level check */

static int *type_, *ndom, (*dom)[4], (*nb)[4];
static int *asg;                 /* -1 = undecided, else the chosen pattern mask */
static int *order;               /* static search order (== Python's MRV choice) */
static int *bat, nbat, *tgt, ntgt;
static int *orm, *andm;          /* OR / AND of the cell's domain masks */
static int (*pass_)[4];          /* pass_[i][e]: exits reachable when entering from e */
static int *stk, *is_tgt;
/* "visited in this ok() call" marks: comparing with a per-call stamp instead
   of clearing the arrays on every search step */
static unsigned *seen_at, *reached_at, *sure_at, stamp;

/* conflict-directed backjumping: when ok() fails it lists the assigned cells
   that caused it (expl); each depth keeps the set of earlier depths its
   failures depend on (conf, a bitset per depth); a dead end jumps straight
   back to the deepest of them, skipping cells that had nothing to do with it */
static int *pos;                 /* depth a cell was assigned at, -1 = unassigned */
static int *expl, nexpl;         /* explanation of the last ok() failure */
static unsigned *expl_at;        /* dedup marks for expl (stamped) */
static int *par_;                /* sure-flood parents, for the powered-path explanation */
static uint64_t *conf;           /* n depths x W words */
static int W, jump_to;

static void *xalloc(size_t size) {
    void *p = calloc(1, size ? size : 1);
    if (!p) { fprintf(stderr, "orphan_solver: out of memory\n"); exit(1); }
    return p;
}

static void free_all(void) {
    free(type_); free(ndom); free(dom); free(nb); free(asg); free(order);
    free(bat); free(tgt); free(orm); free(andm); free(pass_);
    free(stk); free(is_tgt); free(seen_at); free(reached_at); free(sure_at);
    free(pos); free(expl); free(expl_at); free(par_); free(conf);
}

/* 1 open, 0 closed, 2 unknown — like side_state() in Python */
static int side_state(int i, int d) {
    if (asg[i] >= 0) return (asg[i] >> d) & 1;
    int opens  = (orm[i] >> d) & 1;
    int closes = !((andm[i] >> d) & 1);
    if (opens && !closes) return 1;
    if (!opens) return 0;
    return 2;
}

static int any_open(int i, int d) {
    return asg[i] >= 0 ? (asg[i] >> d) & 1 : (orm[i] >> d) & 1;
}

static int exits(int i, int e) {
    if (asg[i] >= 0) return ((asg[i] >> e) & 1) ? (asg[i] & ~(1 << e)) : 0;
    return pass_[i][e];
}

static int sp;

static void blame(int x) {           /* x's assignment took part in the outcome */
    if (x >= 0 && asg[x] >= 0 && expl_at[x] != stamp) {
        expl_at[x] = stamp;
        expl[nexpl++] = x;
    }
}

static void enter(int x, int e) {
    if (x < 0 || x == cand || seen_at[x * 4 + e] == stamp) return;
    blame(x);                        /* entering x (or not) depends on its rotation */
    if (any_open(x, e)) {
        seen_at[x * 4 + e] = stamp;
        stk[sp++] = x * 4 + e;
    }
}

/* Can this partial assignment still end in a win with the candidate unpowered?
 *  1. every lamp must be reachable from a battery, power passing through a
 *     cell only in a way one of its remaining rotations allows, never through
 *     the candidate (direction-aware reachability; it implies the plain
 *     undirected check the Python version also did, so that one is skipped);
 *  2. the candidate must not already be connected to a battery by edges that
 *     are open on both sides for sure. */
static int ok(void) {
    if (++stamp == 0) {                     /* stamp wrapped: really clear once */
        memset(seen_at, 0, sizeof(unsigned) * (size_t)n * 4);
        memset(reached_at, 0, sizeof(unsigned) * (size_t)n);
        memset(sure_at, 0, sizeof(unsigned) * (size_t)n);
        memset(expl_at, 0, sizeof(unsigned) * (size_t)n);
        stamp = 1;
    }
    nexpl = 0;

    /* 1 — stops as soon as every lamp is reached */
    int need = ntgt;
    sp = 0;
    for (int j = 0; j < nbat; j++) {
        int b = bat[j];
        reached_at[b] = stamp;
        blame(b);
        for (int d = 0; d < 4; d++)
            if (any_open(b, d)) enter(nb[b][d], OPP[d]);
    }
    while (sp && need) {
        int s = stk[--sp], x = s / 4, e = s % 4;
        if (reached_at[x] != stamp) {
            reached_at[x] = stamp;
            if (is_tgt[x]) need--;
        }
        int m = exits(x, e);
        for (int y = 0; y < 4; y++)
            if (y != e && ((m >> y) & 1)) enter(nb[x][y], OPP[y]);
    }
    if (need) return 0;       /* expl: every assigned cell the flood touched —
                                 the reached region and its blocked border */

    /* 2 — flood from the batteries over sure edges, stop if it hits the candidate */
    nexpl = 0;
    if (++stamp == 0) {                     /* fresh marks for this part */
        memset(seen_at, 0, sizeof(unsigned) * (size_t)n * 4);
        memset(reached_at, 0, sizeof(unsigned) * (size_t)n);
        memset(sure_at, 0, sizeof(unsigned) * (size_t)n);
        memset(expl_at, 0, sizeof(unsigned) * (size_t)n);
        stamp = 1;
    }
    sp = 0;
    for (int j = 0; j < nbat; j++) {
        sure_at[bat[j]] = stamp;
        par_[bat[j]] = -1;
        stk[sp++] = bat[j];
    }
    while (sp) {
        int x = stk[--sp];
        if (x == cand) {                    /* candidate provably powered */
            for (int y = x; y >= 0; y = par_[y]) blame(y);   /* expl: that path */
            return 0;
        }
        for (int d = 0; d < 4; d++) {
            int y = nb[x][d];
            if (y < 0 || sure_at[y] == stamp) continue;
            if (side_state(x, d) == 1 && side_state(y, OPP[d]) == 1) {
                sure_at[y] = stamp;
                par_[y] = x;
                stk[sp++] = y;
            }
        }
    }
    return 1;
}

#define CONF(d) (conf + (size_t)(d) * (size_t)W)

/* 1 found, -1 budget exceeded, 0 dead end: jump_to = depth to resume at
   (-1 = no solution at all), its conflict set already merged into CONF(jump_to) */
static int backtrack(int depth) {
    steps++;
    if (steps > limit) return -1;
    if ((steps & 0xFFFF) == 0) {
        printf("P %lld\n", steps);
        fflush(stdout);
        if (getppid() == 1) exit(0);          /* parent gone: stop working */
    }
    if (depth == n) return 1;
    int v = order[depth];
    uint64_t *C = CONF(depth);
    memset(C, 0, sizeof(uint64_t) * (size_t)W);
    for (int k = 0; k < ndom[v]; k++) {
        asg[v] = dom[v][k];
        pos[v] = depth;
        if (!ok()) {
            for (int i = 0; i < nexpl; i++) {
                int dd = pos[expl[i]];
                if (dd != depth) C[dd >> 6] |= (uint64_t)1 << (dd & 63);
            }
            continue;
        }
        int r = backtrack(depth + 1);
        if (r) return r;                        /* found (keep asg) or budget */
        if (jump_to < depth) {                  /* this cell isn't to blame: skip it */
            asg[v] = -1; pos[v] = -1;
            return 0;
        }
        /* jump_to == depth: the dead end below depends on this cell — next value */
    }
    asg[v] = -1; pos[v] = -1;
    int h = -1;                                 /* deepest earlier cause */
    for (int w = W - 1; w >= 0 && h < 0; w--)
        if (C[w]) h = w * 64 + 63 - __builtin_clzll(C[w]);
    jump_to = h;
    if (h >= 0) {
        uint64_t *H = CONF(h);
        for (int w = 0; w < W; w++) H[w] |= C[w];
        H[h >> 6] &= ~((uint64_t)1 << (h & 63));
    }
    return 0;
}

static int by_domain_then_index(const void *pa, const void *pb) {
    int a = *(const int *)pa, b = *(const int *)pb;
    if (ndom[a] != ndom[b]) return ndom[a] - ndom[b];
    return a - b;
}

static int read_query(void) {
    char tag[8];
    if (scanf("%7s", tag) != 1) return 0;
    if (strcmp(tag, "Q") != 0) { fprintf(stderr, "orphan_solver: bad input\n"); exit(1); }
    int found_flag;
    if (scanf("%d %d %d %lld %lld %d", &rows, &cols, &cand, &budget, &found_budget,
              &found_flag) != 6) {
        fprintf(stderr, "orphan_solver: bad query header (rebuild: make build-solver)\n");
        exit(1);
    }
    if (found_flag) found_any = 1;
    n = rows * cols;

    type_ = xalloc(sizeof(int) * n);   ndom = xalloc(sizeof(int) * n);
    dom   = xalloc(sizeof(*dom) * n);  nb   = xalloc(sizeof(*nb) * n);
    asg   = xalloc(sizeof(int) * n);   order = xalloc(sizeof(int) * n);
    bat   = xalloc(sizeof(int) * n);   tgt  = xalloc(sizeof(int) * n);
    orm   = xalloc(sizeof(int) * n);   andm = xalloc(sizeof(int) * n);
    pass_ = xalloc(sizeof(*pass_) * n);
    stk   = xalloc(sizeof(int) * n * 4); is_tgt = xalloc(sizeof(int) * n);
    seen_at = xalloc(sizeof(unsigned) * n * 4);
    reached_at = xalloc(sizeof(unsigned) * n); sure_at = xalloc(sizeof(unsigned) * n);
    stamp = 0;
    nbat = ntgt = 0;
    W = (n + 63) / 64;
    pos = xalloc(sizeof(int) * n);  expl = xalloc(sizeof(int) * n);
    expl_at = xalloc(sizeof(unsigned) * n);  par_ = xalloc(sizeof(int) * n);
    conf = xalloc(sizeof(uint64_t) * (size_t)n * (size_t)W);
    for (int i = 0; i < n; i++) pos[i] = -1;

    for (int i = 0; i < n; i++) {
        if (scanf("%d %d", &type_[i], &ndom[i]) != 2 || ndom[i] < 1 || ndom[i] > 4) exit(1);
        orm[i] = 0; andm[i] = 15;
        for (int k = 0; k < ndom[i]; k++) {
            if (scanf("%d", &dom[i][k]) != 1) exit(1);
            orm[i] |= dom[i][k];
            andm[i] &= dom[i][k];
        }
        for (int e = 0; e < 4; e++) {
            pass_[i][e] = 0;
            for (int k = 0; k < ndom[i]; k++)
                if ((dom[i][k] >> e) & 1) pass_[i][e] |= dom[i][k] & ~(1 << e);
        }
        if (type_[i] == T_BATT) bat[nbat++] = i;
        if (type_[i] == T_TARG) { tgt[ntgt++] = i; is_tgt[i] = 1; }
        asg[i] = -1;
        order[i] = i;
    }
    for (int i = 0; i < n; i++) {
        int r = i / cols, c = i % cols;
        for (int d = 0; d < 4; d++) {
            int rr = r + DR[d], cc = c + DC[d];
            nb[i][d] = (rr >= 0 && rr < rows && cc >= 0 && cc < cols) ? rr * cols + cc : -1;
        }
    }
    qsort(order, (size_t)n, sizeof(int), by_domain_then_index);
    return 1;
}

int main(void) {
    while (read_query()) {
        steps = 0;
        limit = (found_any && found_budget < budget) ? found_budget : budget;
        int r = ok() ? backtrack(0) : 0;
        if (r == 1) {
            found_any = 1;
            printf("R unused %lld", steps);
            for (int i = 0; i < n; i++) printf(" %d", asg[i]);
            printf("\n");
        } else if (r < 0) {
            printf(found_any ? "R stop %lld\n" : "R timeout %lld\n", steps);
        } else {
            printf("R ok %lld\n", steps);
        }
        fflush(stdout);
        free_all();
    }
    return 0;
}
