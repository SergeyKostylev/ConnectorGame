/*
 * orphan_solver — C port of the per-tile search in tools/orphan_checker.py
 * (unpowered mode: Solver + optimistic_ok + _directional_reach). Same
 * variable order, same domain order, same pruning, so it visits the same
 * search nodes as the Python version, just much faster.
 *
 * Build:  make build-solver      (cc -O2 -o tools/orphan_solver tools/orphan_solver.c)
 *
 * Protocol (text, one long-lived process per level check; driven by
 * CSolver in orphan_checker.py):
 *
 *   in:   Q <rows> <cols> <candidate> <budget> <found_budget>
 *         then rows*cols cells, row-major:  <type> <ndom> <mask> ... <mask>
 *           type: 0 pipeline/wall, 1 battery, 2 target
 *           mask: open sides, bit 0 up, 1 right, 2 down, 3 left
 *         budget:       steps allowed per tile while no orphan was found yet
 *         found_budget: steps allowed per tile once this process has found an
 *                       orphan (the level is failed; it's only worth
 *                       continuing while tiles are cheap)
 *         Both come with every query, so changing them in Python needs no rebuild.
 *
 *   out:  P <steps>                     progress, every 65536 steps
 *         R ok <steps>                  no win state leaves the candidate unpowered
 *         R timeout <steps>             budget exceeded, no orphan found yet
 *         R stop <steps>                found_budget exceeded after an orphan was found
 *         R unused <steps> <mask>*n     a win state with the candidate unpowered
 *
 * The process exits on end of input, or when its parent dies.
 */
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
static int found_any;            /* this process has already reported an orphan */

static int *type_, *ndom, (*dom)[4], (*nb)[4];
static int *asg;                 /* -1 = undecided, else the chosen pattern mask */
static int *order;               /* static search order (== Python's MRV choice) */
static int *bat, nbat, *tgt, ntgt;
static int *orm, *andm;          /* OR / AND of the cell's domain masks */
static int (*pass_)[4];          /* pass_[i][e]: exits reachable when entering from e */
static int *par, *spar, *reached, *stk;
static unsigned char *seen;

static void *xalloc(size_t size) {
    void *p = calloc(1, size ? size : 1);
    if (!p) { fprintf(stderr, "orphan_solver: out of memory\n"); exit(1); }
    return p;
}

static void free_all(void) {
    free(type_); free(ndom); free(dom); free(nb); free(asg); free(order);
    free(bat); free(tgt); free(orm); free(andm); free(pass_);
    free(par); free(spar); free(reached); free(stk); free(seen);
}

static int find(int *p, int x) {
    while (p[x] != x) { p[x] = p[p[x]]; x = p[x]; }
    return x;
}

static void unite(int *p, int a, int b) {
    int ra = find(p, a), rb = find(p, b);
    if (ra != rb) p[ra] = rb;
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

static void enter(int x, int e) {
    if (x < 0 || x == cand || seen[x * 4 + e]) return;
    if (any_open(x, e)) {
        seen[x * 4 + e] = 1;
        stk[sp++] = x * 4 + e;
    }
}

/* optimistic_ok() + _directional_reach() + the "candidate already powered" test */
static int ok(void) {
    for (int i = 0; i < n; i++) { par[i] = i; spar[i] = i; }
    for (int a = 0; a < n; a++) {
        for (int d = 1; d <= 2; d++) {          /* right, down: each edge once */
            int b = nb[a][d];
            if (b < 0) continue;
            int sa = side_state(a, d), sb = side_state(b, OPP[d]);
            if (a != cand && b != cand && sa != 0 && sb != 0) unite(par, a, b);
            if (sa == 1 && sb == 1) unite(spar, a, b);  /* includes the candidate */
        }
    }
    for (int k = 0; k < ntgt; k++) {
        int rt = find(par, tgt[k]), hit = 0;
        for (int j = 0; j < nbat && !hit; j++) hit = find(par, bat[j]) == rt;
        if (!hit) return 0;
    }

    /* direction-aware reachability */
    memset(seen, 0, (size_t)n * 4);
    memset(reached, 0, sizeof(int) * (size_t)n);
    sp = 0;
    for (int j = 0; j < nbat; j++) {
        int b = bat[j];
        reached[b] = 1;
        for (int d = 0; d < 4; d++)
            if (any_open(b, d)) enter(nb[b][d], OPP[d]);
    }
    while (sp) {
        int s = stk[--sp], x = s / 4, e = s % 4;
        reached[x] = 1;
        int m = exits(x, e);
        for (int y = 0; y < 4; y++)
            if (y != e && ((m >> y) & 1)) enter(nb[x][y], OPP[y]);
    }
    for (int k = 0; k < ntgt; k++)
        if (!reached[tgt[k]]) return 0;

    int ro = find(spar, cand);
    for (int j = 0; j < nbat; j++)
        if (find(spar, bat[j]) == ro) return 0;   /* candidate provably powered */
    return 1;
}

/* 1 found, 0 exhausted, -1 budget exceeded */
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
    for (int k = 0; k < ndom[v]; k++) {
        asg[v] = dom[v][k];
        if (ok()) {
            int r = backtrack(depth + 1);
            if (r) return r;                    /* keep asg on success */
        }
        asg[v] = -1;
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
    if (scanf("%d %d %d %lld %lld", &rows, &cols, &cand, &budget, &found_budget) != 5) {
        fprintf(stderr, "orphan_solver: bad query header (rebuild: make build-solver)\n");
        exit(1);
    }
    n = rows * cols;

    type_ = xalloc(sizeof(int) * n);   ndom = xalloc(sizeof(int) * n);
    dom   = xalloc(sizeof(*dom) * n);  nb   = xalloc(sizeof(*nb) * n);
    asg   = xalloc(sizeof(int) * n);   order = xalloc(sizeof(int) * n);
    bat   = xalloc(sizeof(int) * n);   tgt  = xalloc(sizeof(int) * n);
    orm   = xalloc(sizeof(int) * n);   andm = xalloc(sizeof(int) * n);
    pass_ = xalloc(sizeof(*pass_) * n);
    par   = xalloc(sizeof(int) * n);   spar = xalloc(sizeof(int) * n);
    reached = xalloc(sizeof(int) * n); stk  = xalloc(sizeof(int) * n * 4);
    seen  = xalloc((size_t)n * 4);
    nbat = ntgt = 0;

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
        if (type_[i] == T_TARG) tgt[ntgt++] = i;
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
