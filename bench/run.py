#!/usr/bin/env python3
"""Benchmarks brainfk against other Brainfuck implementations.

Every implementation runs every program in bench/programs. Outputs are checked
against the naive interpreter's before anything is timed. Fast implementations
are timed in rounds that take turns going first, slow ones (the naive
interpreter) after them, and each time is the median of its runs. Prints the
results as Markdown tables.

Implementations:
  - naive:   bench/baselines/naive.c, a plain interpreter (cc -O2)
  - bf2c:    bench/baselines/bf2c.py, Brainfuck translated 1:1 to C (cc -O2)
  - tritium: rdebath's optimizing interpreter/JIT, fetched and built into
             bench/.cache (skip with --no-tritium)
  - brainfk at -O0 to -O3

Needs nasm, ld, a C compiler, cargo, and (for tritium) git, make and libgmp.

    python3 bench/run.py [--runs 7] [--cpu 2] [--no-tritium] [--only mandelbrot,long]
"""

import argparse
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent
PROGRAMS = BENCH / "programs"
CACHE = BENCH / ".cache"
TRITIUM_REPO = "https://github.com/rdebath/Brainfuck"

# A run slower than this is reported as a timeout.
TIMEOUT = 300

# Implementations slower than this (seconds) are timed after all the others.
SLOW = 2.0


def sh(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def cc():
    return os.environ.get("CC") or shutil.which("cc") or "gcc"


def build_brainfk():
    sh("cargo", "build", "--release", "--quiet", cwd=ROOT)
    return ROOT / "target" / "release" / "brainfk"


def build_tritium():
    """Fetches and builds tritium into bench/.cache, once."""
    src = CACHE / "Brainfuck"
    exe = src / "tritium" / "bfi.out"
    if not exe.exists():
        print("building tritium (once, into bench/.cache)...", file=sys.stderr)
        CACHE.mkdir(exist_ok=True)
        if not src.exists():
            sh("git", "clone", "--quiet", "--depth", "1", TRITIUM_REPO, str(src))
        sh("make", "-j8", cwd=src / "tritium", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return exe


class Impl:
    """One implementation: how to build a program for it, and the command to run it."""

    def __init__(self, name, prepare):
        self.name = name
        # prepare(program, workdir) -> (command, compile seconds or None)
        self.prepare = prepare


def implementations(args, workdir):
    impls = []

    naive = workdir / "naive"
    sh(cc(), "-O2", "-o", str(naive), str(BENCH / "baselines" / "naive.c"))
    impls.append(Impl("naive interpreter (C, -O2)", lambda prog, _: ([str(naive), str(prog)], None)))

    def bf2c(prog, out):
        c_file = out / f"{prog.stem}.c"
        exe = out / f"{prog.stem}-bf2c"
        start = time.perf_counter()
        with open(c_file, "w") as f:
            sh(sys.executable, str(BENCH / "baselines" / "bf2c.py"), str(prog), stdout=f)
        sh(cc(), "-O2", "-o", str(exe), str(c_file))
        return [str(exe)], time.perf_counter() - start

    impls.append(Impl("Brainfuck → C, cc -O2", bf2c))

    if not args.no_tritium:
        tritium = build_tritium()
        # 8-bit cells and EOF sets the cell to 0, like brainfk.
        base = [str(tritium), "-b", "-z"]
        impls.append(Impl("tritium, interpreter (-r)", lambda prog, _: (base + ["-r", str(prog)], None)))
        impls.append(Impl("tritium, default (JIT)", lambda prog, _: (base + [str(prog)], None)))

    brainfk = build_brainfk()
    for level in range(4):

        def compile_at(prog, out, level=level):
            exe = out / f"{prog.stem}-O{level}"
            start = time.perf_counter()
            sh(str(brainfk), str(prog), f"-O{level}", "-o", str(exe))
            return [str(exe)], time.perf_counter() - start

        impls.append(Impl(f"brainfk -O{level}", compile_at))

    return impls


def run_once(cmd, input_bytes, cpu, capture):
    """Runs `cmd` once, returning (seconds, stdout if `capture`).

    Waits for the process with a blocking wait, not `subprocess.run(timeout=...)`:
    that polls with sleeps of up to 50 ms, which would round every time up.
    """
    if cpu is not None:
        cmd = ["taskset", "-c", str(cpu)] + cmd
    with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout:
        stdin.write(input_bytes)
        stdin.seek(0)
        start = time.perf_counter()
        process = subprocess.Popen(
            cmd,
            stdin=stdin,
            stdout=stdout if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        timer = threading.Timer(TIMEOUT, process.kill)
        timer.start()
        returncode = process.wait()
        elapsed = time.perf_counter() - start
        timed_out = not timer.is_alive()
        timer.cancel()

        if timed_out:
            raise subprocess.TimeoutExpired(cmd, TIMEOUT)
        if returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} exited with {returncode}")
        stdout.seek(0)
        return elapsed, stdout.read() if capture else None


def fmt_time(t):
    if t is None:
        return "–"
    if t == "timeout":
        return f"> {TIMEOUT} s"
    if t < 0.01:
        return f"{t * 1000:.1f} ms"
    return f"{t:.2f} s"


def table(title, rows, programs):
    lines = [f"### {title}", "", "| | " + " | ".join(p.stem for p in programs) + " |"]
    lines.append("|---|" + "---:|" * len(programs))
    for name, cells in rows:
        lines.append(f"| {name} | " + " | ".join(fmt_time(cells.get(p.stem)) for p in programs) + " |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=7, help="timing rounds per program (the median is reported)")
    parser.add_argument("--cpu", type=int, help="pin every run to this CPU with taskset")
    parser.add_argument("--cooldown", type=float, default=10, help="seconds to pause before timing each program")
    parser.add_argument("--no-tritium", action="store_true", help="don't fetch, build or run tritium")
    parser.add_argument("--only", help="comma-separated program names to run")
    args = parser.parse_args()

    programs = sorted(PROGRAMS.glob("*.b"))
    if args.only:
        wanted = set(args.only.split(","))
        programs = [p for p in programs if p.stem in wanted]

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        impls = implementations(args, workdir)
        runtimes = {impl.name: {} for impl in impls}
        compile_times = {impl.name: {} for impl in impls}

        for prog in programs:
            input_file = prog.with_suffix(".in")
            input_bytes = input_file.read_bytes() if input_file.exists() else b""
            expected = None
            slow = set()

            # Build everything and check the outputs before timing anything.
            commands = {}
            for impl in impls:
                cmd, compile_time = impl.prepare(prog, workdir)
                compile_times[impl.name][prog.stem] = compile_time
                try:
                    check_time, output = run_once(cmd, input_bytes, args.cpu, capture=True)
                except subprocess.TimeoutExpired:
                    runtimes[impl.name][prog.stem] = "timeout"
                    print(f"{prog.stem:>12}  {impl.name}: timed out", file=sys.stderr)
                    continue
                if expected is None:
                    expected = output
                elif output != expected:
                    sys.exit(f"{impl.name} printed the wrong output for {prog.name}")
                commands[impl.name] = cmd
                if check_time > SLOW:
                    slow.add(impl.name)

            # Most laptops slow down as they heat up, and seconds of a slow baseline
            # heat them up a lot. So: cool down after the checks, time the fast
            # implementations in rounds that take turns going first (so none always
            # runs right after another), and only then the slow ones.
            time.sleep(args.cooldown)
            times = {name: [] for name in commands}
            fast = [name for name in commands if name not in slow]
            for i in range(args.runs):
                k = i % len(fast)
                for name in fast[k:] + fast[:k]:
                    times[name].append(run_once(commands[name], input_bytes, args.cpu, capture=False)[0])
            for name in commands:
                if name in slow:
                    for _ in range(args.runs):
                        times[name].append(run_once(commands[name], input_bytes, args.cpu, capture=False)[0])

            for name, ts in times.items():
                runtimes[name][prog.stem] = statistics.median(ts)
                print(f"{prog.stem:>12}  {name}: {fmt_time(runtimes[name][prog.stem])}", file=sys.stderr)

    cpu = platform.processor() or platform.machine()
    try:
        with open("/proc/cpuinfo") as f:
            cpu = next(line.split(":", 1)[1].strip() for line in f if line.startswith("model name"))
    except (OSError, StopIteration):
        pass
    pinned = f", pinned to CPU {args.cpu}" if args.cpu is not None else ""

    print(f"Median of {args.runs} runs on {cpu}{pinned}. Outputs were checked to match.\n")
    print(table("Run time", [(i.name, runtimes[i.name]) for i in impls], programs))
    print()
    compiled = [(i.name, compile_times[i.name]) for i in impls if any(compile_times[i.name].values())]
    print(table("Compile time (including nasm and ld for brainfk)", compiled, programs))


if __name__ == "__main__":
    main()
