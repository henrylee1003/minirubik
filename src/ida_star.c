/* IDA* version of minirubik: same input, same output line as mini.c.
 *
 * Differences from mini.c: no heap, no recursion, no full distance table.
 * Static data is about 50 KiB instead of a 3.5 MiB table plus a 49 MiB queue.
 * This file is the C blueprint of src/solver.s (the RV32I version).
 *
 * Build: gcc -std=c99 -O2 -o ida_star ida_star.c
 * Usage: ./ida_star 21345671111111
 */
#include <stdio.h>
#include <string.h>

enum { C = 7, NP = 5040, NT = 729, FACES = 3, MAX_DEPTH = 11, UNSEEN = 0xFF };
typedef struct {
    unsigned char p[C], o[C];
} state_t;

/* All memory is static and small. */
static unsigned short perm_mv[FACES][NP], twist_mv[FACES][NT]; /* 34.6 KiB */
static unsigned char perm_prune[NP], twist_prune[NT];          /*  5.6 KiB */
static unsigned short queue[NP];                               /*  9.8 KiB */

/* Same quarter turn as mini.c. */
static state_t turn(state_t s, int f)
{
    static const char map[][15] = {
        "14203561202100",
        "01245630001212",
        "02531460000000",
    };
    state_t t;
    for (int i = 0; i < C; ++i) {
        int j = map[f][i] - '0';
        t.p[i] = s.p[j];
        t.o[i] = (s.o[j] + map[f][i + C] - '0') % 3;
    }
    return t;
}

/* mini.c ranks both parts into one number; here they stay separate. */
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

/* Move tables: "state number -> state number after one quarter turn". */
static void build_move_tables(void)
{
    for (unsigned r = 0; r < NP; ++r) {
        state_t s = {{0}, {0}};
        unsigned char pool[C] = {0, 1, 2, 3, 4, 5, 6};
        static const unsigned fact[C] = {720, 120, 24, 6, 2, 1, 1};
        unsigned x = r;
        for (int i = 0; i < C; ++i) { /* undo rank_perm */
            unsigned d = x / fact[i];
            x %= fact[i];
            s.p[i] = pool[d];
            memmove(pool + d, pool + d + 1, C - 1 - d);
        }
        for (int f = 0; f < FACES; ++f) {
            state_t t = turn(s, f);
            perm_mv[f][r] = (unsigned short) rank_perm(t.p);
        }
    }
    for (unsigned r = 0; r < NT; ++r) {
        state_t s = {{0, 1, 2, 3, 4, 5, 6}, {0}};
        unsigned x = r, sum = 0;
        for (int i = 5; i >= 0; --i, x /= 3)
            sum += s.o[i] = x % 3;
        s.o[6] = (3 - sum % 3) % 3;
        for (int f = 0; f < FACES; ++f) {
            state_t t = turn(s, f);
            twist_mv[f][r] = (unsigned short) rank_twist(t.o);
        }
    }
}

/* Small BFS over one coordinate only: a lower bound, not the real distance. */
static void build_prune(const unsigned short *mv, unsigned char *prune,
                        unsigned n)
{
    unsigned head = 0, tail = 1;
    memset(prune, UNSEEN, n);
    prune[0] = 0;
    queue[0] = 0;
    while (head < tail) {
        unsigned cur = queue[head++];
        for (int f = 0; f < FACES; ++f) {
            unsigned next = cur;
            for (int k = 0; k < 3; ++k) {
                next = mv[f * n + next];
                if (prune[next] == UNSEEN) {
                    prune[next] = prune[cur] + 1;
                    queue[tail++] = (unsigned short) next;
                }
            }
        }
    }
}

static int heuristic(unsigned perm, unsigned twist)
{
    int a = perm_prune[perm], b = twist_prune[twist];
    return a > b ? a : b;
}

/* One DFS frame; the explicit stack replaces recursion. */
typedef struct {
    unsigned short perm, twist;         /* this node */
    unsigned short cur_perm, cur_twist; /* child being built */
    signed char last, face, turns;      /* loop state */
} frame_t;

/* IDA* main loop. Returns the length and fills path[] (move = face*3 + n). */
static int search(unsigned perm, unsigned twist, unsigned char *path)
{
    frame_t stack[MAX_DEPTH + 1];
    for (int bound = heuristic(perm, twist); bound <= MAX_DEPTH; ++bound) {
        int depth = 0;
        if (bound == 0)
            return 0;
        stack[0] = (frame_t) {.perm = perm, .twist = twist, .last = -1};
        while (depth >= 0) {
            frame_t *f = &stack[depth];
            if (f->face == FACES) { /* all moves tried: pop */
                --depth;
                continue;
            }
            if (f->face == f->last || f->turns == 3) { /* next face */
                ++f->face;
                f->turns = 0;
                continue;
            }
            if (f->turns == 0) {
                f->cur_perm = f->perm;
                f->cur_twist = f->twist;
            }
            /* One more quarter turn: two table lookups per child. */
            f->cur_perm = perm_mv[f->face][f->cur_perm];
            f->cur_twist = twist_mv[f->face][f->cur_twist];
            int n = f->turns++;
            int h = heuristic(f->cur_perm, f->cur_twist);
            if (depth + 1 + h > bound) /* cannot finish in time: prune */
                continue;
            path[depth] = (unsigned char) (f->face * 3 + n);
            if (h == 0 && depth + 1 == bound) /* h == 0 means solved */
                return bound;
            stack[depth + 1] = (frame_t) {
                .perm = f->cur_perm, .twist = f->cur_twist, .last = f->face};
            ++depth;
        }
    }
    return -1;
}

int main(int argc, char **argv)
{
    state_t s, inv;
    unsigned seen = 0, sum = 0;
    unsigned char path[MAX_DEPTH];
    if (argc != 2 || strlen(argv[1]) != 14)
        return 2;
    for (int i = 0; i < C; ++i) {
        unsigned p = (unsigned) (argv[1][i] - '1');
        unsigned o = (unsigned) (argv[1][i + C] - '1');
        if (p >= C || o >= 3 || seen >> p & 1)
            return 2;
        s.p[i] = p;
        s.o[i] = o;
        seen |= 1U << p;
        sum += o;
    }
    if (sum % 3)
        return 2;

    build_move_tables();
    build_prune(&perm_mv[0][0], perm_prune, NP);
    build_prune(&twist_mv[0][0], twist_prune, NT);

    /* Search from the inverse state in BFS move order: the first hit is the
     * same path mini.c's BFS would pick, just read backwards. */
    for (int i = 0; i < C; ++i)
        inv.p[s.p[i]] = i;
    for (int i = 0; i < C; ++i)
        inv.o[i] = (3 - s.o[inv.p[i]]) % 3;
    int len = search(rank_perm(inv.p), rank_twist(inv.o), path);
    if (len < 0)
        return 1;

    const char *sep = "";
    for (int i = len - 1; i >= 0; --i) { /* reverse, and invert each move */
        printf("%s%c%s", sep, "RBD"[path[i] / 3],
               (const char *[]) {"'", "2", ""}[path[i] % 3]);
        sep = " ";
    }
    return putchar('\n') < 0 || fflush(stdout) || ferror(stdout);
}
