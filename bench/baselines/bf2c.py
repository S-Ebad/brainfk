#!/usr/bin/env python3
"""Translates Brainfuck to C, one statement per command, for a C compiler to optimize.

This is the usual "let gcc do the work" baseline: no Brainfuck-level optimizations,
everything is left to the C compiler. Same semantics as brainfk: 8-bit wrapping
cells, a 30000-cell tape, and EOF sets the cell to 0.

    python3 bf2c.py program.b > program.c && cc -O2 -o program program.c
"""

import sys

STATEMENTS = {
    "+": "++*p;",
    "-": "--*p;",
    ">": "++p;",
    "<": "--p;",
    ".": "putchar(*p);",
    ",": "{ int c = getchar(); *p = c == EOF ? 0 : c; }",
    "[": "while (*p) {",
    "]": "}",
}


def main():
    if len(sys.argv) != 2:
        sys.exit(f"usage: {sys.argv[0]} program.b")

    with open(sys.argv[1], encoding="latin-1") as f:
        commands = [c for c in f.read() if c in STATEMENTS]

    print("#include <stdio.h>")
    print("static unsigned char tape[30000];")
    print("int main(void) {")
    print("unsigned char *p = tape;")
    for c in commands:
        print(STATEMENTS[c])
    print("return 0;")
    print("}")


if __name__ == "__main__":
    main()
