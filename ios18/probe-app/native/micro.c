// SPDX-License-Identifier: MIT
// Per-operation cost of instructions, library calls and system calls inside
// the guest. Rows that are close on real hardware and far apart here show
// what the engine or the guest kernel runs unusually slowly.
// With an argument, only the rows whose name contains it run.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <linux/futex.h>
#include <time.h>
#include <unistd.h>

static const char *only;
static double now(void) {
    struct timespec t;
    syscall(SYS_clock_gettime, CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e9 + t.tv_nsec;
}
#define KEEP(v) __asm__ volatile("" : : "r"(v) : "memory")
#define ROW(name, count, body) do { \
    if (only == NULL || strstr(name, only) != NULL) { \
        long repeat = only != NULL ? 4 : 1; \
        double start = now(); \
        for (long r = 0; r < repeat; r++) \
            for (long i = 0; i < (count); i++) { body; } \
        double each = (now() - start) / ((count) * repeat); \
        printf("micro %-46s %9.1f ns\n", name, each); fflush(stdout); \
    } \
} while (0)

__attribute__((noinline)) static uint64_t leaf(uint64_t x) { KEEP(x); return x * 3 + 1; }
__attribute__((noinline)) static uint64_t framed(uint64_t x) { return leaf(x) + 1; }
static __thread uint64_t thread_local_value;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_key_t key;
static uint64_t cell;
static void *held[100000];

// A row that may raise SIGILL runs in a child.
#define CHILD_ROW(name, count, body) do { \
    if (only == NULL || strstr(name, only) != NULL) { \
        fflush(stdout); \
        pid_t child = fork(); \
        if (child == 0) { const char *saved = only; only = NULL; ROW(name, count, body); only = saved; _exit(0); } \
        int status = 0; waitpid(child, &status, 0); \
        if (!WIFEXITED(status)) printf("micro %-46s not available (signal %d)\n", name, WTERMSIG(status)); \
    } \
} while (0)

int main(int argc, char **argv) {
    only = argc > 1 ? argv[1] : NULL;
    uint64_t x = 88172645463325252ull, sum = 0, v = 0;
    ROW("empty loop", 20000000L, { KEEP(i); });
    ROW("xorshift arithmetic", 20000000L, { x ^= x << 13; x ^= x >> 7; x ^= x << 17; KEEP(x); });
    ROW("unpredictable branch", 20000000L, { x ^= x << 13; x ^= x >> 7; x ^= x << 17; if (x & 1) sum += 3; else sum ^= x; KEEP(sum); });
    ROW("udiv", 20000000L, { v = (x | 1) / ((uint64_t)i | 3); KEEP(v); });
    ROW("leaf call", 20000000L, { sum += leaf(i); });
    ROW("call with a frame", 20000000L, { sum += framed(i); });
    ROW("mrs tpidr_el0", 20000000L, { __asm__ volatile("mrs %0, tpidr_el0" : "=r"(v)); KEEP(v); });
    ROW("thread-local read+write", 20000000L, { thread_local_value += i; KEEP(&thread_local_value); });
    ROW("mrs nzcv", 20000000L, { __asm__ volatile("mrs %0, nzcv" : "=r"(v)); KEEP(v); });
    ROW("mrs fpcr", 20000000L, { __asm__ volatile("mrs %0, fpcr" : "=r"(v)); KEEP(v); });
    ROW("msr fpcr", 20000000L, { __asm__ volatile("mrs %0, fpcr\nmsr fpcr, %0" : "=&r"(v)); KEEP(v); });
    CHILD_ROW("mrs cntvct_el0", 20000000L, { __asm__ volatile("mrs %0, cntvct_el0" : "=r"(v)); KEEP(v); });
    CHILD_ROW("mrs ctr_el0", 20000000L, { __asm__ volatile("mrs %0, ctr_el0" : "=r"(v)); KEEP(v); });
    CHILD_ROW("crc32cx", 20000000L, { __asm__ volatile(".arch armv8-a+crc\ncrc32cx %w0, %w0, %1" : "+r"(v) : "r"(x)); KEEP(v); });
    CHILD_ROW("ldaddal (LSE atomic add)", 20000000L, { __asm__ volatile(".arch armv8.1-a+lse\nldaddal %1, %0, [%2]" : "=&r"(v) : "r"(x), "r"(&cell) : "memory"); });
    CHILD_ROW("casal (LSE compare and swap)", 20000000L, { v = cell; __asm__ volatile(".arch armv8.1-a+lse\ncasal %0, %1, [%2]" : "+r"(v) : "r"(x), "r"(&cell) : "memory"); });
    ROW("ldaxr+stlxr pair", 20000000L, { uint32_t failed; __asm__ volatile("ldaxr %0, [%2]\nadd %0, %0, #1\nstlxr %w1, %0, [%2]" : "=&r"(v), "=&r"(failed) : "r"(&cell) : "memory"); });
    ROW("paciasp+autiasp hints", 20000000L, { __asm__ volatile("hint #25\nhint #29" : : : "x30", "x17"); });
    ROW("bti hint", 20000000L, { __asm__ volatile("hint #34"); });
    ROW("isb", 2000000L, { __asm__ volatile("isb"); });
    static float vector[16] __attribute__((aligned(64)));
    ROW("NEON load, multiply-add, store", 20000000L, { __asm__ volatile("ld1 {v0.4s}, [%0]\nfmla v1.4s, v0.4s, v0.4s\nst1 {v1.4s}, [%0]" : : "r"(vector) : "v0", "v1", "memory"); });
    double f = 1.0;
    ROW("double multiply-add", 20000000L, { f = f * 1.0000001 + 0.5; KEEP(f); });
    static char zero_block[4096] __attribute__((aligned(4096)));
    CHILD_ROW("dc zva", 5000000L, { __asm__ volatile("dc zva, %0" : : "r"(zero_block) : "memory"); });

    size_t bytes = 1 << 16;
    uint64_t *mapped = mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    uint64_t *heap = malloc(bytes);
    memset(mapped, 0, bytes); memset(heap, 0, bytes);
    volatile uint64_t *volatile p = mapped;
    ROW("load+store, untagged mapping", 20000000L, { p[i & 8191] += i; });
    p = heap;
    ROW("load+store, heap pointer", 20000000L, { p[i & 8191] += i; });
    ROW("pair store and load on the stack", 20000000L, { __asm__ volatile("stp x9, x10, [sp, #-16]!\nldp x9, x10, [sp], #16" : : : "x9", "x10", "memory"); });

    pthread_key_create(&key, NULL); pthread_setspecific(key, &cell);
    ROW("libc: pthread_getspecific", 10000000L, { v = (uintptr_t)pthread_getspecific(key); KEEP(v); });
    ROW("libc: gettid", 10000000L, { v = gettid(); KEEP(v); });
    ROW("libc: errno", 10000000L, { v = errno; KEEP(v); });
    ROW("libc: mutex lock+unlock", 10000000L, { pthread_mutex_lock(&mutex); pthread_mutex_unlock(&mutex); });
    char a[4200], b[4200]; memset(a, 'a', sizeof a); a[255] = 0;
    ROW("libc: strlen 8 bytes", 10000000L, { v = strlen(a + 247); KEEP(v); });
    ROW("libc: strlen 255 bytes", 3000000L, { v = strlen(a + (i & 7)); KEEP(v); });
    ROW("libc: memcpy 16 bytes", 10000000L, { memcpy(b, a + (i & 63), 16); KEEP(b); });
    ROW("libc: memcpy 4096 bytes", 1000000L, { memcpy(b, a + (i & 63), 4096); KEEP(b); });
    ROW("libc: memset 64 bytes", 10000000L, { memset(b + (i & 63), 0, 64); KEEP(b); });
    ROW("libc: memset 4096 bytes", 1000000L, { memset(b + (i & 63), 0, 4096); KEEP(b); });
    ROW("libc: malloc+free 32 bytes", 3000000L, { void *m = malloc(32); KEEP(m); free(m); });
    ROW("libc: malloc+free 256 bytes", 3000000L, { void *m = malloc(256); KEEP(m); free(m); });
    ROW("libc: malloc 48 bytes, kept", 100000L, { held[i] = malloc(48); });
    ROW("libc: free 48 bytes", 100000L, { free(held[i]); held[i] = NULL; });
    ROW("libc: calloc+free 64 bytes", 3000000L, { void *m = calloc(1, 64); KEEP(m); free(m); });
    ROW("libc: snprintf of an integer", 1000000L, { snprintf(b, 64, "%ld", i); KEEP(b); });
    ROW("libc: snprintf of a string", 1000000L, { snprintf(b, 64, "%s", "settings"); KEEP(b); });
    ROW("libc: strtol", 2000000L, { const char *text = "1234567"; KEEP(text); v = strtol(text, NULL, 10); KEEP(v); });

    struct timespec t; struct timeval tv;
    ROW("libc: clock_gettime MONOTONIC", 1000000L, { clock_gettime(CLOCK_MONOTONIC, &t); });
    ROW("system call: getpid", 1000000L, { v = syscall(SYS_getpid); });
    ROW("system call: getuid", 1000000L, { v = syscall(SYS_getuid); });
    ROW("system call: clock_gettime MONOTONIC", 1000000L, { syscall(SYS_clock_gettime, CLOCK_MONOTONIC, &t); });
    ROW("system call: clock_gettime BOOTTIME", 1000000L, { syscall(SYS_clock_gettime, CLOCK_BOOTTIME, &t); });
    ROW("system call: clock_gettime REALTIME", 1000000L, { syscall(SYS_clock_gettime, CLOCK_REALTIME, &t); });
    ROW("system call: clock_gettime MONOTONIC_COARSE", 1000000L, { syscall(SYS_clock_gettime, CLOCK_MONOTONIC_COARSE, &t); });
    ROW("system call: clock_gettime THREAD_CPUTIME", 1000000L, { syscall(SYS_clock_gettime, CLOCK_THREAD_CPUTIME_ID, &t); });
    ROW("system call: gettimeofday", 1000000L, { syscall(SYS_gettimeofday, &tv, NULL); });
    int null = open("/dev/null", O_RDWR), zero = open("/dev/zero", O_RDONLY), poll = epoll_create1(0);
    ROW("system call: write 1 byte to /dev/null", 500000L, { v = write(null, a, 1); });
    ROW("system call: read 1 byte of /dev/zero", 500000L, { v = read(zero, b, 1); });
    ROW("system call: fcntl F_GETFL", 500000L, { v = fcntl(null, F_GETFL); });
    ROW("system call: ioctl refused", 500000L, { v = ioctl(null, 0x5401, b); });
    ROW("system call: dup+close", 300000L, { int copy = dup(null); close(copy); });
    ROW("system call: epoll_pwait, nothing ready", 300000L, { struct epoll_event event; v = epoll_pwait(poll, &event, 1, 0, NULL); });
    ROW("system call: futex wake, nobody waiting", 500000L, { v = syscall(SYS_futex, &cell, FUTEX_WAKE, 1, NULL, NULL, 0); });
    ROW("system call: sched_yield", 300000L, { sched_yield(); });
    ROW("system call: mmap+munmap one page", 100000L, { void *m = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0); munmap(m, 4096); });
    ROW("page fault: touch a fresh page", 50000L, { char *m = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0); m[0] = 1; munmap(m, 4096); });
    KEEP(sum);
    return 0;
}
