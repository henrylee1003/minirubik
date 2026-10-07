/* Stage 3: price each C-level refinement in operation counts.
 *
 * Three ways to generate one child in the same IDA* (same nodes, same answer):
 *   V0  cubie arrays: turn() the arrays, then rank both halves for the lookup
 *   V1  coordinates + move tables, each child built from the parent
 *       (n + 1 lookups per coordinate for the n-th turn of a face)
 *   V2  coordinates + move tables, cumulative quarter turns (1 lookup each)
 * Counters are incremented where the operation happens, so the totals are
 * measured, not estimated.
 *
 * Build: gcc -std=gnu99 -O2 -o stage3_variants stage3_variants.c
 * Usage: ./stage3_variants 21345671111111
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

enum { C = 7, NP = 5040, NT = 729, F = 3, UNSEEN = 0xFF, MAXD = 11 };
typedef struct {
    unsigned char p[C], o[C];
} state_t;

static uint16_t pmv[F][NP], tmv[F][NT];
static uint8_t pprune[NP], tprune[NT];
static uint64_t n_mul, n_mod, n_load, n_copy, n_cmp, n_nodes;
static int counting;

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
    if (counting) {
        n_copy += 2 * C; /* p[] and o[] elements moved */
        n_mod += C;      /* one % 3 per twist */
        n_load += 2 * C; /* map[] source index and twist delta */
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
    if (counting) {
        n_cmp += 21;
        n_mul += C;
    }
    return r;
}

static unsigned rank_twist(const unsigned char *o)
{
    unsigned r = 0;
    for (int i = 0; i < 6; ++i)
        r = r * 3 + o[i];
    if (counting)
        n_mul += 6;
    return r;
}

static void build_tables(void)
{
    static const unsigned fact[C] = {720, 120, 24, 6, 2, 1, 1};
    static uint16_t queue[NP];
    for (unsigned r = 0; r < NP; ++r) {
        state_t s = {{0}, {0}};
        unsigned char pool[C] = {0, 1, 2, 3, 4, 5, 6};
        unsigned x = r;
        for (int i = 0; i < C; ++i) {
            unsigned d = x / fact[i];
            x %= fact[i];
            s.p[i] = pool[d];
            memmove(pool + d, pool + d + 1, C - 1 - d);
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
        for (int f = 0; f < F; ++f)
            tmv[f][r] = (uint16_t) rank_twist(turn(s, f).o);
    }
    for (int which = 0; which < 2; ++which) {
        const uint16_t *mv = which ? &tmv[0][0] : &pmv[0][0];
        uint8_t *prune = which ? tprune : pprune;
        unsigned n = which ? NT : NP, head = 0, tail = 1;
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
}

typedef struct {
    state_t s, cur;                 /* V0 */
    uint16_t perm, twist, cp, ct;   /* V1, V2 */
    int8_t last, face, turns;
} frame_t;

static int search(int variant, state_t start)
{
    static frame_t stack[MAXD + 1];
    unsigned p0 = rank_perm(start.p), t0 = rank_twist(start.o);
    int h0 = pprune[p0] > tprune[t0] ? pprune[p0] : tprune[t0];
    for (int bound = h0; bound <= MAXD; ++bound) {
        int depth = 0;
        if (bound == 0)
            return 0;
        memset(&stack[0], 0, sizeof(stack[0]));
        stack[0].s = start;
        stack[0].perm = (uint16_t) p0;
        stack[0].twist = (uint16_t) t0;
        stack[0].last = -1;
        while (depth >= 0) {
            frame_t *f = &stack[depth];
            unsigned p, t;
            if (f->face == F) {
                --depth;
                continue;
            }
            if (f->face == f->last || f->turns == 3) {
                ++f->face;
                f->turns = 0;
                continue;
            }
            if (variant == 0) {
                if (f->turns == 0)
                    f->cur = f->s;
                f->cur = turn(f->cur, f->face);
                p = rank_perm(f->cur.p);
                t = rank_twist(f->cur.o);
            } else if (variant == 1) {
                p = f->perm;
                t = f->twist;
                for (int k = 0; k <= f->turns; ++k) {
                    p = pmv[f->face][p];
                    t = tmv[f->face][t];
                    n_load += 2;
                    n_mul += 2; /* face * NP and face * NT in the index */
                }
            } else {
                if (f->turns == 0) {
                    f->cp = f->perm;
                    f->ct = f->twist;
                }
                p = f->cp = pmv[f->face][f->cp];
                t = f->ct = tmv[f->face][f->ct];
                n_load += 2; /* base pointer bumped per face: no multiply */
            }
            ++f->turns;
            ++n_nodes;
            n_load += 2; /* the two pruning lookups */
            int h = pprune[p] > tprune[t] ? pprune[p] : tprune[t];
            if (depth + 1 + h > bound)
                continue;
            if (h == 0 && depth + 1 == bound)
                return bound;
            memset(&stack[depth + 1], 0, sizeof(stack[0]));
            stack[depth + 1].s = f->cur;
            stack[depth + 1].perm = (uint16_t) p;
            stack[depth + 1].twist = (uint16_t) t;
            stack[depth + 1].last = f->face;
            ++depth;
        }
    }
    return -1;
}

int main(int argc, char **argv)
{
    static const char *const name[] = {
        "V0 cubie arrays + rank per child", "V1 move tables, from parent",
        "V2 move tables, cumulative"};
    state_t s, inv;
    if (argc != 2 || strlen(argv[1]) != 14)
        return 2;
    for (int i = 0; i < C; ++i) {
        s.p[i] = argv[1][i] - '1';
        s.o[i] = argv[1][i + C] - '1';
    }
    for (int i = 0; i < C; ++i)
        inv.p[s.p[i]] = i;
    for (int i = 0; i < C; ++i)
        inv.o[i] = (3 - s.o[inv.p[i]]) % 3;
    build_tables();
    printf("%-34s %4s %9s %10s %10s %10s %10s %10s %8s\n", "variant", "len", "nodes",
           "mul", "mod 3", "loads", "copies", "compares", "ms");
    for (int v = 0; v < 3; ++v) {
        n_mul = n_mod = n_load = n_copy = n_cmp = n_nodes = 0;
        counting = 1;
        clock_t a = clock();
        int len = search(v, inv);
        double ms = 1000.0 * (clock() - a) / CLOCKS_PER_SEC;
        counting = 0;
        printf("%-34s %4d %9llu %10llu %10llu %10llu %10llu %10llu %8.1f\n", name[v], len,
               (unsigned long long) n_nodes, (unsigned long long) n_mul,
               (unsigned long long) n_mod, (unsigned long long) n_load,
               (unsigned long long) n_copy, (unsigned long long) n_cmp, ms);
        printf("%-34s %4s %9s %10.1f %10.1f %10.1f %10.1f %10.1f\n", "  per node", "", "",
               (double) n_mul / n_nodes, (double) n_mod / n_nodes, (double) n_load / n_nodes,
               (double) n_copy / n_nodes, (double) n_cmp / n_nodes);
    }
    return 0;
}
