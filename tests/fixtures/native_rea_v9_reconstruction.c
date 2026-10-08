/* Independently expressed candidate reconstruction of an owned benchmark.
 * The testing fixture is deliberately not generated from a REA decompilation.
 * Its equivalence is measured by deterministic differential execution.
 */
#include <stdint.h>
#include <stdio.h>

__attribute__((noinline))
int32_t feature_score(int32_t tempo, int32_t energy) {
    const int64_t value = 31LL * energy + 17LL * tempo;
    int32_t result = (int32_t)(((value % 997) + 997) % 997);
    if (energy < 0) result = (result + 950) % 997;
    else if (energy >= 250 && tempo >= 120) result = result + 123;
#ifdef INTRODUCE_DEFECT
    if (tempo % 97 == 0) result += 1;
#endif
    return result;
}
int main(void) {
    int tempo, energy;
    while (scanf("%d%d", &tempo, &energy) == 2) {
        printf("%d\n", feature_score(tempo, energy));
    }
    return 0;
}
