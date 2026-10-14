# brainfk

[![CI](https://github.com/S-Ebad/brainfk/actions/workflows/ci.yml/badge.svg)](https://github.com/S-Ebad/brainfk/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An optimizing [Brainfuck](https://en.wikipedia.org/wiki/Brainfuck) compiler for
x86-64 Linux, written in Rust. It compiles straight to NASM assembly and links a
small static executable, with no runtime and no libc.

On the classic Brainfuck benchmarks, its `-O2` output runs 40–900× faster than
a plain interpreter, and on `mandelbrot.b` it beats both C compiled with gcc and
an optimizing JIT ([numbers below](#benchmarks)).

- **Four optimization levels**, from a direct translation up to running the
  program at compile time.
- **Loop optimizations**: clear, scan and multiply loops become straight-line
  code, pointer moves fold into addressing offsets, dead loops disappear.
- **Configurable tape**: any size, and a choice of undefined, abort or
  wrap-around when a program leaves it.
- **Friendly errors**: unmatched brackets are reported with line, column and a
  caret, rustc-style.
- **Tested** against reference interpreters with 120+ tests, including fuzzing
  at every optimization level.

## Install

You need x86-64 Linux, a Rust toolchain, `nasm` and `ld` (from binutils):

```sh
sudo apt install nasm binutils    # Debian/Ubuntu
sudo pacman -S nasm binutils      # Arch

cargo install --git https://github.com/S-Ebad/brainfk
```

Or from a clone: `cargo build --release`, which puts the compiler in
`target/release/brainfk`.

## Usage

```sh
brainfk hello.b -O2            # compile to ./a.out
./a.out
Hello World!

brainfk hello.b -O2 -o hello   # name the executable
brainfk hello.b --emit asm     # just the assembly (a.asm), or --emit obj for a.o
```

| Option | Default | |
|---|---|---|
| `-O <0-3>` | `0` | Optimization level, see below |
| `-o <file>` | `a.out` / `a.asm` / `a.o` | Output file |
| `--emit <exe\|obj\|asm>` | `exe` | What to produce |
| `--tape-size <n>` | `30000` | Number of cells, up to 2³¹−1 |
| `--bounds <mode>` | `undefined` | What happens when a cell off the tape is touched |
| `-s, --step-limit <n>` | `1000000` | How long `-O3` runs the program at compile time |

### Semantics

- Cells are 8 bits and wrap around (`255 + 1 = 0`).
- The tape has 30000 cells by default, and the pointer starts on the first.
- `,` at end of input sets the cell to 0.
- Every character other than `+-<>.,[]` is a comment.
- Unmatched brackets are compile errors:

```
error: unmatched `]` at line 3, column 1
  |
3 | ]
  | ^

Error: could not compile due to 1 previous error(s)
```

## Optimization levels

| Level | What it does |
|---|---|
| `-O0` | One instruction (or so) per command. |
| `-O1` | Merges runs: `+++++` is one `add`, `>>>` one pointer move. |
| `-O2` | Rewrites common loop shapes and folds pointer moves into offsets (below). |
| `-O3` | Everything in `-O2`, then runs the program at compile time. |

**`-O2`** works on a small set of extra opcodes:

- **Offsets.** Pointer moves around cell operations become addressing offsets, so
  `>>++<<` is `add byte [rbx+2], 2` and the pointer never moves. Loops whose body
  doesn't move the pointer overall run at an offset too.
- **Clear loops.** `[-]` and `[+]` become a store of 0, and neighbouring stores
  are combined into wider ones (eight cleared cells are one `qword` store).
- **Scan loops.** `[>]`, `[<<<]` and so on become a search for a zero cell,
  checking four cells per iteration (one with checked bounds).
- **Multiply loops.** Loops that only add constants and whose counter steps by an
  odd amount run a fixed number of times, computed with a modular inverse, so
  `[->++>+++<<]` becomes two multiplies and a clear:

  ```nasm
  ; -O0                            ; -O2
  .loop_0:                         movzx eax, byte [rbx]
    dec byte [rbx]                 imul ecx, eax, 2
    inc rbx                        add byte [rbx+1], cl
    inc byte [rbx]                 imul ecx, eax, 3
    inc byte [rbx]                 add byte [rbx+2], cl
    inc rbx                        mov byte [rbx+0], 0
    inc byte [rbx]
    inc byte [rbx]
    inc byte [rbx]
    dec rbx
    dec rbx
    cmp byte [rbx], 0
    jne .loop_0
  ```

- **Dead loops.** A loop that starts on a cell known to be 0 (at the start of the
  program, or right after another loop) can't run and is removed. That includes
  the comment blocks many programs start with.
- **Unrolling.** Loops of only cell operations run their body twice per
  iteration, moving the pointer once (not with checked bounds).

**`-O3`** runs the optimized program inside the compiler, for up to `--step-limit`
steps. It stops at the first `,` (the input isn't known yet), and the executable
carries on from exactly that point: its output so far, the tape, the pointer,
even the middle of a loop. A program that doesn't read input and finishes within
the limit compiles to nothing but its output:

```nasm
; brainfk hello.b -O3 --emit asm (comments added)
_start:
  mov eax, 1          ; write(1, output, 13)
  mov edi, 1
  lea rsi, [rel output]
  mov edx, 13
  syscall
  mov eax, 60         ; exit(0)
  xor edi, edi
  syscall
output:
  db 72, 101, 108, 108, 111, 32, 87, 111, 114, 108, 100, 33, 10
```

## Tape bounds

What `--bounds` does when the program reads or writes a cell off the tape
(moving the pointer off it is fine, as long as nothing is touched there):

| Mode | Behaviour | Cost |
|---|---|---|
| `undefined` | Not checked: like C, anything can happen. | None |
| `abort` | Prints what was output so far, then an error, and exits with code 1. | A range check per straight-line stretch |
| `wrap` | The tape is circular: left of the first cell is the last one. | Every pointer move and offset access is wrapped |

`abort` behaves identically at every optimization level, even for accesses the
optimizer removes: `<+-` touches cell −1 and aborts, although `+-` compiles to
nothing.

## How it works

```
source ─► lexer ─► resolver ─► optimizer ─► evaluator (-O3) ─► codegen ─► nasm + ld
```

| Stage | File | |
|---|---|---|
| Lexer | [`src/lexer.rs`](src/lexer.rs) | Turns commands into tokens, keeping each one's position for errors. |
| Resolver | [`src/resolver.rs`](src/resolver.rs) | Matches brackets and gives every loop an id. Runs before optimizing, so errors refer to the source as written. |
| Optimizer | [`src/optimizer.rs`](src/optimizer.rs) | The `-O1` and `-O2` passes. Every pass emits through one helper that merges neighbouring tokens. |
| Evaluator | [`src/evaluator.rs`](src/evaluator.rs) | Runs optimized tokens at compile time for `-O3` and records where to resume. |
| Codegen | [`src/codegen.rs`](src/codegen.rs) | Emits NASM. Every loop checks its cell once per iteration, and codegen tracks what the flags and registers hold to skip redundant compares and loads. |
| Errors | [`src/errors.rs`](src/errors.rs) | Rustc-style reports, aligned correctly around tabs and wide characters. |

Output goes through a 4 KiB buffer and is flushed before every read, so prompts
show up before the program waits for input.

## Benchmarks

Run time of each program, median of 7 runs on an Intel Core Ultra 7 155U, pinned
to one performance core. Every implementation printed exactly the same output.

| | mandelbrot | factor | hanoi | long |
|---|---:|---:|---:|---:|
| Plain interpreter (C, `-O2`) | 13.00 s | 9.38 s | 7.88 s | 10.31 s |
| tritium, interpreter (`-r`) | 1.41 s | 0.82 s | 20 ms | 40 ms |
| Brainfuck → C, `gcc -O2` | 0.66 s | 0.19 s | **3.5 ms** | 60 ms |
| tritium, JIT (default) | 0.40 s | **0.16 s** | 20 ms | **6.5 ms** |
| **brainfk `-O0`** | 0.96 s | 0.74 s | 4.06 s | 3.79 s |
| **brainfk `-O1`** | 0.74 s | 0.66 s | 0.80 s | 2.07 s |
| **brainfk `-O2`** | **0.33 s** | **0.16 s** | 9.0 ms | 0.18 s |

- The **plain interpreter** ([`bench/baselines/naive.c`](bench/baselines/naive.c))
  is what an unoptimized implementation costs.
- **Brainfuck → C** ([`bench/baselines/bf2c.py`](bench/baselines/bf2c.py))
  translates each command to one C statement and leaves all the optimizing to gcc.
- **[tritium](https://github.com/rdebath/Brainfuck/tree/master/tritium)** is a
  mature optimizing interpreter with a JIT, run with 8-bit cells and EOF as 0 to
  match brainfk.

gcc and tritium win `hanoi.b` and `long.b`, whose time goes into nested loops
their optimizers can simplify further than brainfk's (which only rewrites
innermost loops so far). `-O3` gives
the same times as `-O2` here: these programs either read input right away or run
for far longer than its default step limit.

brainfk compiles every program in under 0.4 s, assembler and linker included.
gcc needs 1.4 s for `mandelbrot.b` and 7.8 s for `hanoi.b`.

To reproduce:

```sh
python3 bench/run.py --cpu 2      # pin to one core; see --help
```

The script builds every implementation, checks that they all print exactly the
same output for every program, then times them. The programs and their authors
are listed in [`bench/programs`](bench/programs/README.md).

## Development

```sh
cargo test                    # needs nasm and ld
cargo clippy --all-targets
cargo fmt
```

The tests compile and run programs at every optimization level and compare them
with reference interpreters, including random programs built from the shapes
the optimizer looks for, and random step limits so `-O3` stops and resumes all
over the place. CI runs formatting, clippy and the tests on every push.

## License

[MIT](LICENSE). The benchmark programs in `bench/programs` belong to their
authors and aren't covered by it.
