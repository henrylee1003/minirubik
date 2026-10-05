/* Control for the "computed vs measured" gap: allocate and touch exactly
 * N bytes, so peak RSS minus N is the fixed cost of the process itself.
 *
 * Build: gcc -O2 -o rss_control rss_control.c
 * Usage: /usr/bin/time -f "%M KB" ./rss_control 18405414
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    size_t n = argc > 1 ? strtoul(argv[1], NULL, 10) : 0;
    unsigned char *p = malloc(n);
    if (!p)
        return 1;
    memset(p, 1, n); /* touch every page so it becomes resident */
    printf("%u\n", p[n / 2]);
    free(p);
    return 0;
}
