// SPDX-License-Identifier: MIT
// Per-operation cost of common code patterns inside the guest. Ratios between
// rows that are close on real hardware show which pattern the engine runs
// unusually slowly.
#define _GNU_SOURCE
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e9 + t.tv_nsec;
}
static volatile uint64_t sink;
#define ROW(name, count, body) do { \
    double start = now(); \
    for (long i = 0; i < (count); i++) { body; } \
    double each = (now() - start) / (count); \
    printf("micro %-44s %9.1f ns\n", name, each); fflush(stdout); \
} while (0)

__attribute__((noinline)) static uint64_t leaf(uint64_t x) { return x * 3 + 1; }
static uint64_t (*volatile indirect)(uint64_t) = leaf;
static __thread uint64_t thread_local_value;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static atomic_ulong counter;
static atomic_int reference = 1;

static void *spin(void *unused) { (void)unused; for (;;) pause(); return NULL; }

int main(void) {
    uint64_t x = 88172645463325252ull, sum = 0;
    ROW("xorshift arithmetic", 20000000L, { x ^= x << 13; x ^= x >> 7; x ^= x << 17; });
    sink = x;
    ROW("direct call", 20000000L, { sum += leaf(i); });
    ROW("indirect call", 20000000L, { sum += indirect(i); });
    double f = 1.0;
    ROW("double multiply-add", 20000000L, { f = f * 1.0000001 + 0.5; });
    sink = (uint64_t)f;

    size_t bytes = 1 << 16;
    uint64_t *mapped = mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    uint64_t *heap = malloc(bytes);
    memset(mapped, 0, bytes); memset(heap, 0, bytes);
    printf("micro heap pointer %p, mapped pointer %p\n", (void *)heap, (void *)mapped);
    volatile uint64_t *volatile p = mapped;
    ROW("load+store, untagged mapping", 20000000L, { p[i & 8191] += i; });
    p = heap;
    ROW("load+store, heap pointer", 20000000L, { p[i & 8191] += i; });
    p = (uint64_t *)((uintptr_t)mapped | (0xb4ull << 56));
    ROW("load+store, mapping with a tag byte", 20000000L, { p[i & 8191] += i; });
    volatile uint8_t *volatile bytes_pointer = (uint8_t *)heap;
    ROW("byte load+store, heap", 20000000L, { bytes_pointer[i & 65535]++; });
    volatile uint64_t stack_slot = 0;
    ROW("load+store, stack", 20000000L, { stack_slot += i; });

    ROW("thread-local read+write", 20000000L, { thread_local_value += i; });
    ROW("atomic fetch_add", 10000000L, { atomic_fetch_add(&counter, 1); });
    ROW("atomic reference up and down", 10000000L, {
        atomic_fetch_add_explicit(&reference, 1, memory_order_relaxed);
        if (atomic_fetch_sub_explicit(&reference, 1, memory_order_acq_rel) == 1) abort(); });
    ROW("atomic compare-exchange", 10000000L, {
        unsigned long expected = atomic_load(&counter);
        atomic_compare_exchange_strong(&counter, &expected, expected + 1); });
    ROW("mutex lock+unlock, one thread", 10000000L, { pthread_mutex_lock(&mutex); pthread_mutex_unlock(&mutex); });
    ROW("malloc+free 32 bytes", 3000000L, { void *m = malloc(32); sink = (uintptr_t)m; free(m); });
    ROW("malloc+free 4096 bytes", 1000000L, { void *m = malloc(4096); sink = (uintptr_t)m; free(m); });
    char a[256], b[256]; memset(a, 'a', 255); a[255] = 0;
    ROW("memcpy 64 bytes", 5000000L, { memcpy(b, a + (i & 63), 64); });
    ROW("strlen 255 bytes", 3000000L, { sink = strlen(a + (i & 7)); });
    ROW("snprintf of an integer", 1000000L, { snprintf(b, sizeof b, "%ld", i); });
    ROW("strtol of an integer", 2000000L, { sink = strtol("1234567", NULL, 10); });
    char *big_a = malloc(1 << 20), *big_b = malloc(1 << 20); memset(big_a, 1, 1 << 20);
    ROW("memcpy 1 MiB", 300L, { memcpy(big_b, big_a, 1 << 20); });
    ROW("clock_gettime", 1000000L, { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); });
    ROW("getpid system call", 300000L, { sink = syscall(SYS_getpid); });
    unsigned state = 0; static const unsigned char program[16] = {0,1,2,3,1,0,3,2,2,2,1,3,0,0,1,3};
    ROW("switch dispatch", 20000000L, { switch (program[i & 15]) { case 0: state += 3; break; case 1: state ^= i; break; case 2: state <<= 1; break; default: state |= 1; } });
    sink = state + sum;

    // The same atomic and allocation rows with a second thread alive.
    pthread_t other; pthread_create(&other, NULL, spin, NULL);
    ROW("two threads: atomic fetch_add", 10000000L, { atomic_fetch_add(&counter, 1); });
    ROW("two threads: mutex lock+unlock", 10000000L, { pthread_mutex_lock(&mutex); pthread_mutex_unlock(&mutex); });
    ROW("two threads: malloc+free 32 bytes", 3000000L, { void *m = malloc(32); sink = (uintptr_t)m; free(m); });
    ROW("two threads: xorshift arithmetic", 20000000L, { x ^= x << 13; x ^= x >> 7; x ^= x << 17; });
    return 0;
}
