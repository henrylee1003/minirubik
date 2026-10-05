/* Host-side oracle and correctness gates H1-H3, plus heuristic comparison.
 *
 * Builds the exact BFS distance table over all 3,674,160 states (host only,
 * never linked into the RV32I program) and checks the search against it.
 *
 * Build: gcc -std=c99 -O2 -fopenmp -o host_gates host_gates.c
 * Usage: ./host_gates            (all gates; H3 takes minutes)
 *        ./host_gates quick      (skip the all-states H3 run)
 */
#include <omp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { C = 7, NP = 5040, NT = 729, NS = NP * NT, F = 3, UNSEEN = 0xFF, MAXD = 11 };
enum { H_ZERO, H_WRONG, H_TWIST, H_PERM, H_MAX, H_BIG, H_BIGMAX, H_KINDS };
static const char *const KIND[H_KINDS] = {
    "h = 0 (plain IDDFS)",        "ceil(W/4), W = wrong cubies",
    "twist PDB only (729)",       "perm PDB only (5040)",
    "max(perm, twist)  [chosen]", "perm x 27 PDB (136080)",
    "max(perm x 27, twist)",
};

typedef struct {
    unsigned char p[C], o[C];
} state_t;

static uint16_t pmv[F][NP], tmv[F][NT];
static uint8_t pprune[NP], tprune[NT];
static uint8_t wrongp[NP], wrongt[NT]; /* bit i set: cubie slot i is wrong */
static uint8_t big[NP * 27];           /* min exact distance over last 3 twists */
static uint8_t *dist;                  /* exact oracle, host only */

static state_t turn(state_t s, int f)
{
    static const char map[][15] = {
        "14203561202100", "01245630001212", "02531460000000"};
    state_t t;
    for (int i = 0; i < C; ++i) {
        int j = map[f][i] - '0';
        t.p[i] = s.p[j];
        t.o[i] = (s.o[j] + map[f][i + C] - '0') % 3;
    }
    return t;
}

static unsigned rank_perm(const unsigned char *p)
{
    unsigned r = 0;
    for (int i = 0; i < C; ++i) {
        int n = 0;
        for (int j = i + 1; j < C; ++j)
            n += p[j] < p[i];
        r = r * (C - i) + n;
    }
    return r;
}

static unsigned rank_twist(const unsigned char *o)
{
    unsigned r = 0;
    for (int i = 0; i < 6; ++i)
        r = r * 3 + o[i];
    return r;
}

static void build_tables(void)
{
    static const unsigned fact[C] = {720, 120, 24, 6, 2, 1, 1};
    for (unsigned r = 0; r < NP; ++r) {
        state_t s = {{0}, {0}};
        unsigned char pool[C] = {0, 1, 2, 3, 4, 5, 6};
        unsigned x = r;
        for (int i = 0; i < C; ++i) {
            unsigned d = x / fact[i];
            x %= fact[i];
            s.p[i] = pool[d];
            memmove(pool + d, pool + d + 1, C - 1 - d);
            if (s.p[i] != i)
                wrongp[r] |= 1u << i;
        }
        for (int f = 0; f < F; ++f)
            pmv[f][r] = (uint16_t) rank_perm(turn(s, f).p);
    }
    for (unsigned r = 0; r < NT; ++r) {
        state_t s = {{0, 1, 2, 3, 4, 5, 6}, {0}};
        unsigned x = r, sum = 0;
        for (int i = 5; i >= 0; --i, x /= 3)
            sum += s.o[i] = x % 3;
        s.o[6] = (3 - sum % 3) % 3;
        for (int i = 0; i < C; ++i)
            if (s.o[i])
                wrongt[r] |= 1u << i;
        for (int f = 0; f < F; ++f)
            tmv[f][r] = (uint16_t) rank_twist(turn(s, f).o);
    }
}

/* Same BFS shape as the RV32I build_prune. */
static void build_prune(const uint16_t *mv, uint8_t *prune, unsigned n)
{
    static uint16_t queue[NP];
    unsigned head = 0, tail = 1;
    memset(prune, UNSEEN, n);
    prune[0] = 0;
    queue[0] = 0;
    while (head < tail) {
        unsigned cur = queue[head++];
        for (int f = 0; f < F; ++f) {
            unsigned next = cur;
            for (int k = 0; k < 3; ++k) {
                next = mv[f * n + next];
                if (prune[next] == UNSEEN) {
                    prune[next] = prune[cur] + 1;
                    queue[tail++] = (uint16_t) next;
                }
            }
        }
    }
}

static void build_oracle(void)
{
    uint32_t *queue = malloc(sizeof(*queue) * NS);
    unsigned head = 0, tail = 1;
    dist = malloc(NS);
    memset(dist, UNSEEN, NS);
    dist[0] = 0;
    queue[0] = 0;
    while (head < tail) {
        unsigned cur = queue[head++], p0 = cur / NT, t0 = cur % NT;
        for (int f = 0; f < F; ++f) {
            unsigned p = p0, t = t0;
            for (int k = 0; k < 3; ++k) {
                p = pmv[f][p];
                t = tmv[f][t];
                if (dist[p * NT + t] == UNSEEN) {
                    dist[p * NT + t] = dist[cur] + 1;
                    queue[tail++] = p * NT + t;
                }
            }
        }
    }
    free(queue);
    if (tail != NS) {
        printf("oracle incomplete: %u states\n", tail);
        exit(1);
    }
    memset(big, UNSEEN, sizeof(big));
    for (unsigned s = 0; s < NS; ++s) {
        unsigned i = (s / NT) * 27 + (s % NT) / 27;
        if (dist[s] < big[i])
            big[i] = dist[s];
    }
}

static inline int heuristic(int kind, unsigned p, unsigned t)
{
    int a, b;
    switch (kind) {
    case H_ZERO:
        return 0;
    case H_WRONG:
        return (__builtin_popcount(wrongp[p] | wrongt[t]) + 3) / 4;
    case H_TWIST:
        return tprune[t];
    case H_PERM:
        return pprune[p];
    case H_MAX:
        a = pprune[p], b = tprune[t];
        return a > b ? a : b;
    case H_BIG:
        return big[p * 27 + t / 27];
    default:
        a = big[p * 27 + t / 27], b = tprune[t];
        return a > b ? a : b;
    }
}

typedef struct {
    uint16_t perm, twist, cur_perm, cur_twist;
    int8_t last, face, turns;
} frame_t;

/* Same IDA* as src/ida_star.c and src/solver.s; counts generated children.
 * skip_same = 0 keeps all 9 moves at every node (to price that pruning). */
static int ida(int kind, int skip_same, unsigned perm, unsigned twist,
               uint64_t *nodes, uint64_t *per_bound)
{
    frame_t stack[MAXD + 1];
    *nodes = 0;
    for (int bound = heuristic(kind, perm, twist); bound <= MAXD; ++bound) {
        int depth = 0;
        uint64_t before = *nodes;
        if (bound == 0 && perm == 0 && twist == 0)
            return 0;
        stack[0] = (frame_t) {.perm = perm, .twist = twist, .last = -1};
        while (depth >= 0) {
            frame_t *f = &stack[depth];
            if (f->face == F) {
                --depth;
                continue;
            }
            if (f->face == f->last || f->turns == 3) {
                ++f->face;
                f->turns = 0;
                continue;
            }
            if (f->turns == 0) {
                f->cur_perm = f->perm;
                f->cur_twist = f->twist;
            }
            f->cur_perm = pmv[f->face][f->cur_perm];
            f->cur_twist = tmv[f->face][f->cur_twist];
            ++f->turns;
            ++*nodes;
            int h = heuristic(kind, f->cur_perm, f->cur_twist);
            if (depth + 1 + h > bound)
                continue;
            if (depth + 1 == bound) {
                if (f->cur_perm == 0 && f->cur_twist == 0) {
                    if (per_bound)
                        per_bound[bound] = *nodes - before;
                    return bound;
                }
                continue;
            }
            stack[depth + 1] = (frame_t) {.perm = f->cur_perm,
                                          .twist = f->cur_twist,
                                          .last = skip_same ? f->face : -1};
            ++depth;
        }
        if (per_bound)
            per_bound[bound] = *nodes - before;
    }
    return -1;
}

/* Search start for an input string = rank of its inverse (as in solver.s). */
static void start_of(const char *text, unsigned *perm, unsigned *twist)
{
    state_t s, inv;
    for (int i = 0; i < C; ++i) {
        s.p[i] = text[i] - '1';
        s.o[i] = text[i + C] - '1';
    }
    for (int i = 0; i < C; ++i)
        inv.p[s.p[i]] = i;
    for (int i = 0; i < C; ++i)
        inv.o[i] = (3 - s.o[inv.p[i]]) % 3;
    *perm = rank_perm(inv.p);
    *twist = rank_twist(inv.o);
}

static void gate_h2(const char *name, const uint8_t *tab, unsigned n)
{
    unsigned hist[16] = {0}, max = 0, unseen = 0;
    for (unsigned i = 0; i < n; ++i) {
        if (tab[i] == UNSEEN) {
            ++unseen;
            continue;
        }
        ++hist[tab[i]];
        if (tab[i] > max)
            max = tab[i];
    }
    printf("H2 %-12s entries %6u  unpopulated %u  solved entry %u  max %u  histogram",
           name, n, unseen, tab[0], max);
    for (unsigned d = 0; d <= max; ++d)
        printf(" %u", hist[d]);
    printf("  %s\n", unseen == 0 && tab[0] == 0 ? "PASS" : "FAIL");
}

int main(int argc, char **argv)
{
    int quick = argc > 1 && !strcmp(argv[1], "quick");
    double t0 = omp_get_wtime();
    build_tables();
    build_prune(&pmv[0][0], pprune, NP);
    build_prune(&tmv[0][0], tprune, NT);
    build_oracle();
    printf("oracle built in %.2f s\n", omp_get_wtime() - t0);

    /* Distance distribution (cross-check with report.md and Jaap's page). */
    unsigned long count[MAXD + 2] = {0};
    for (unsigned s = 0; s < NS; ++s)
        ++count[dist[s]];
    printf("distance distribution:");
    for (int d = 0; d <= MAXD; ++d)
        printf(" %d:%lu", d, count[d]);
    printf("\n\n");

    /* H2: tables fully populated, solved entry, maximum. */
    gate_h2("perm_prune", pprune, NP);
    gate_h2("twist_prune", tprune, NT);
    gate_h2("perm x 27", big, NP * 27);
    int bij = 1;
    for (int f = 0; f < F; ++f) {
        static uint8_t seen[NP];
        memset(seen, 0, sizeof(seen));
        for (unsigned r = 0; r < NP; ++r)
            seen[pmv[f][r]] = 1;
        for (unsigned r = 0; r < NP; ++r)
            bij &= seen[r];
        memset(seen, 0, sizeof(seen));
        for (unsigned r = 0; r < NT; ++r)
            seen[tmv[f][r]] = 1;
        for (unsigned r = 0; r < NT; ++r)
            bij &= seen[r];
    }
    printf("H2 move tables: every face table is a bijection  %s\n\n", bij ? "PASS" : "FAIL");

    /* H1: admissibility over all states, plus how tight each heuristic is. */
    printf("H1 %-30s %5s %8s %10s %10s\n", "heuristic", "max h", "mean h", "mean d-h", "h > d");
    for (int k = 1; k < H_KINDS; ++k) {
        unsigned long over = 0, sum = 0, gap = 0;
        int max = 0;
        for (unsigned s = 0; s < NS; ++s) {
            int h = heuristic(k, s / NT, s % NT);
            over += h > dist[s];
            sum += h;
            gap += dist[s] - h;
            if (h > max)
                max = h;
        }
        printf("H1 %-30s %5d %8.3f %10.3f %10lu  %s\n", KIND[k], max, (double) sum / NS,
               (double) gap / NS, over, over ? "FAIL" : "PASS");
    }

    /* Node counts for the assignment vector under every heuristic. */
    unsigned p, t;
    uint64_t nodes, per_bound[MAXD + 1];
    start_of("21345671111111", &p, &t);
    printf("\nvector 21345671111111 (distance %d)\n", dist[p * NT + t]);
    printf("%-30s %6s %14s %10s\n", "heuristic", "length", "nodes", "seconds");
    for (int k = 0; k < H_KINDS; ++k) {
        double a = omp_get_wtime();
        int len = ida(k, 1, p, t, &nodes, NULL);
        printf("%-30s %6d %14llu %10.2f\n", KIND[k], len, (unsigned long long) nodes,
               omp_get_wtime() - a);
    }
    memset(per_bound, 0, sizeof(per_bound));
    ida(H_MAX, 1, p, t, &nodes, per_bound);
    printf("chosen heuristic, nodes per bound:");
    for (int b = 0; b <= MAXD; ++b)
        if (per_bound[b])
            printf(" %d:%llu", b, (unsigned long long) per_bound[b]);
    printf("\n");
    ida(H_MAX, 0, p, t, &nodes, NULL);
    printf("chosen heuristic without the same-face skip (9 moves everywhere): %llu nodes\n",
           (unsigned long long) nodes);

    /* All distance-11 states for the table-based heuristics. */
    printf("\nall %lu distance-11 states\n", count[MAXD]);
    printf("%-30s %12s %12s %12s\n", "heuristic", "min nodes", "mean nodes", "max nodes");
    for (int k = H_TWIST; k < H_KINDS; ++k) {
        uint64_t lo = UINT64_MAX, hi = 0, sum = 0;
        #pragma omp parallel for schedule(dynamic, 8) reduction(+:sum)
        for (unsigned s = 0; s < NS; ++s) {
            if (dist[s] != MAXD)
                continue;
            uint64_t n;
            ida(k, 1, s / NT, s % NT, &n, NULL);
            sum += n;
            #pragma omp critical
            {
                if (n < lo)
                    lo = n;
                if (n > hi)
                    hi = n;
            }
        }
        printf("%-30s %12llu %12.0f %12llu\n", KIND[k], (unsigned long long) lo,
               (double) sum / count[MAXD], (unsigned long long) hi);
        fflush(stdout);
    }
    if (quick)
        return 0;

    /* H3: every state, solution length must equal the exact distance. */
    for (int k = H_MAX; k < H_KINDS; k += 2) {
        uint64_t sum[MAXD + 1] = {0}, max[MAXD + 1] = {0};
        unsigned long wrong = 0;
        double a = omp_get_wtime();
        #pragma omp parallel
        {
            uint64_t lsum[MAXD + 1] = {0}, lmax[MAXD + 1] = {0};
            unsigned long lwrong = 0;
            #pragma omp for schedule(dynamic, 4096) nowait
            for (unsigned s = 0; s < NS; ++s) {
                uint64_t n;
                int len = ida(k, 1, s / NT, s % NT, &n, NULL);
                lwrong += len != dist[s];
                lsum[dist[s]] += n;
                if (n > lmax[dist[s]])
                    lmax[dist[s]] = n;
            }
            #pragma omp critical
            for (int d = 0; d <= MAXD; ++d) {
                sum[d] += lsum[d];
                if (lmax[d] > max[d])
                    max[d] = lmax[d];
                wrong += d == 0 ? lwrong : 0;
            }
        }
        printf("\nH3 %s: %d states searched in %.1f s with %d threads, wrong lengths %lu  %s\n",
               KIND[k], NS, omp_get_wtime() - a, omp_get_max_threads(), wrong,
               wrong ? "FAIL" : "PASS");
        printf("%8s %10s %14s %14s\n", "distance", "states", "mean nodes", "max nodes");
        for (int d = 0; d <= MAXD; ++d)
            printf("%8d %10lu %14.0f %14llu\n", d, count[d], (double) sum[d] / count[d],
                   (unsigned long long) max[d]);
        fflush(stdout);
    }
    return 0;
}
