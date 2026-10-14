# Benchmark programs

These are the classic Brainfuck optimization benchmarks, as collected in Mats
Linander's [bfoptimization](https://github.com/matslina/bfoptimization). They're
third-party programs and are **not** covered by this project's license: each
belongs to its author, under the terms stated in the file (if any).

| Program | Author | What it does | License |
|---|---|---|---|
| `mandelbrot.b` | Erik Bosman | Prints a 128×48 ASCII Mandelbrot set. Generated from C preprocessor macros. | none stated |
| `hanoi.b` | Clifford Wolf | Solves the Towers of Hanoi with VT100 animation. Compiled from a higher-level language. | none stated |
| `factor.b` | Brian Raiter | Factors an arbitrarily large number read from stdin (`factor.in`: 133333333333337 = 397 × 1279 × 262589699). | GPL, see the file's header |
| `long.b` | Oleg Mazonka | Nested loops that do nothing useful for a long time. Written as a benchmark. | none stated |

`<name>.in`, when present, is the program's standard input.
