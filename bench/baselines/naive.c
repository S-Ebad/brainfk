// A plain Brainfuck interpreter: the baseline the compiler is measured against.
//
// No optimizations beyond matching brackets up front. Same semantics as brainfk:
// 8-bit wrapping cells, a 30000-cell tape, and EOF sets the cell to 0.
//
//     cc -O2 -o naive naive.c && ./naive program.b < input

#include <stdio.h>
#include <stdlib.h>

#define TAPE_SIZE 30000

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s program.b\n", argv[0]);
        return 2;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror(argv[1]);
        return 1;
    }

    // Keep only the eight commands.
    size_t len = 0, cap = 4096;
    char *code = malloc(cap);
    for (int c; (c = fgetc(f)) != EOF;) {
        switch (c) {
        case '+': case '-': case '<': case '>':
        case '.': case ',': case '[': case ']':
            if (len == cap) code = realloc(code, cap *= 2);
            code[len++] = (char)c;
        }
    }
    fclose(f);

    // Partner of every bracket.
    size_t *jump = malloc(len * sizeof *jump + 1);
    size_t *stack = malloc(len * sizeof *stack + 1), depth = 0;
    for (size_t i = 0; i < len; i++) {
        if (code[i] == '[') {
            stack[depth++] = i;
        } else if (code[i] == ']') {
            if (depth == 0) {
                fprintf(stderr, "unmatched ]\n");
                return 1;
            }
            size_t j = stack[--depth];
            jump[i] = j;
            jump[j] = i;
        }
    }
    if (depth != 0) {
        fprintf(stderr, "unmatched [\n");
        return 1;
    }

    static unsigned char tape[TAPE_SIZE];
    unsigned char *p = tape;

    for (size_t ip = 0; ip < len; ip++) {
        switch (code[ip]) {
        case '+': ++*p; break;
        case '-': --*p; break;
        case '>': ++p; break;
        case '<': --p; break;
        case '.': putchar(*p); break;
        case ',': {
            int c = getchar();
            *p = c == EOF ? 0 : (unsigned char)c;
            break;
        }
        case '[': if (!*p) ip = jump[ip]; break;
        case ']': if (*p) ip = jump[ip]; break;
        }
    }

    return 0;
}
