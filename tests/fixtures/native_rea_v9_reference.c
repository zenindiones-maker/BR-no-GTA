/* Synthetic owned reference logic for REA/Ghidra V9. License: MIT.
 * Never run arbitrary binaries; this fixture is compiled from reviewed code.
 */
#include <stdint.h>
#include <stdio.h>

__attribute__((noinline))
int32_t feature_score(int32_t tempo, int32_t energy) {
    int64_t linear = (int64_t)tempo * 17 + (int64_t)energy * 31;
    int64_t m = linear % 997;
    if (m < 0) m += 997;
    if (tempo >= 120 && energy >= 250) m += 123;
    if (energy < 0) m = (m + 997 - 47) % 997;
    return (int32_t)m;
}
int main(void) {
    int tempo, energy;
    while (scanf("%d%d", &tempo, &energy) == 2) {
        printf("%d\n", feature_score(tempo, energy));
    }
    return 0;
}
