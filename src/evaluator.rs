use crate::lexer::{Token, TokenKind};

/// How many steps -O3 runs a program for at compile time before giving up, unless
/// `--step-limit` says otherwise. That's about 3 seconds of compile time for a
/// program that never finishes, and enough to run all of `mandelbrot.b`.
///
/// A step is one token, or one cell moved by a `Scan`.
pub const DEFAULT_STEP_LIMIT: u64 = 2_000_000_000;

/// The state a program is in after running part of it at compile time.
pub struct Evaluation {
    /// Everything the program printed.
    pub output: Vec<u8>,
    /// Where the compiled program has to carry on, or `None` if the program finished.
    pub resume: Option<Resume>,
}

pub struct Resume {
    /// The token to run next.
    pub index: usize,
    /// The pointer, as a cell index. It can be off the tape if the program moved
    /// there without touching a cell yet.
    pub pointer: isize,
    /// The start of the tape, up to the last cell that isn't 0. The rest is 0.
    pub tape: Vec<u8>,
}

impl Evaluation {
    /// The state before anything ran, which is where compiling without -O3 starts.
    pub fn start() -> Self {
        Self {
            output: Vec::new(),
            resume: Some(Resume {
                index: 0,
                pointer: 0,
                tape: Vec::new(),
            }),
        }
    }
}

/// -O3: runs the program at compile time for up to `step_limit` steps, on a tape of
/// `tape_size` cells.
///
/// Stops early at the first `,` (input isn't known yet), and before any op that
/// would touch a cell off the tape: depending on `--bounds` that's undefined, an
/// error or wraps around, which is left to the compiled program. If the program
/// finishes, all that's left of it is its output.
pub fn evaluate(tokens: &[Token], step_limit: u64, tape_size: usize) -> Evaluation {
    use TokenKind::*;

    let partner = match_loops(tokens);
    // Tapes up to this size are allocated whole (the OS only backs the pages that get
    // used), so accesses never have to grow it. Larger ones grow as they're used.
    const ALLOCATED: usize = 1 << 24;
    let mut tape: Vec<u8> = vec![0; tape_size.min(ALLOCATED)];
    let mut pointer: isize = 0;
    let mut output = Vec::new();
    let mut index = 0;
    let mut steps = 0;

    // Index on the tape of the cell at `offset` from the pointer, if it's on the tape.
    let at = |pointer: isize, offset: isize| -> Option<usize> {
        usize::try_from(pointer + offset)
            .ok()
            .filter(|&i| i < tape_size)
    };
    // The cell at index `i` (on the tape), growing the used part to reach it.
    fn cell(tape: &mut Vec<u8>, i: usize) -> &mut u8 {
        if i >= tape.len() {
            tape.resize(i + 1, 0);
        }
        &mut tape[i]
    }

    'run: while index < tokens.len() {
        if steps >= step_limit {
            break;
        }
        steps += 1;

        match *tokens[index].kind() {
            Add(n) => {
                let Some(i) = at(pointer, 0) else { break };
                let c = cell(&mut tape, i);
                *c = c.wrapping_add(n);
            }
            AddAt(offset, n) => {
                let Some(i) = at(pointer, offset) else { break };
                let c = cell(&mut tape, i);
                *c = c.wrapping_add(n);
            }
            Move(n) => pointer += n,
            Set(offset, n) => {
                let Some(i) = at(pointer, offset) else { break };
                *cell(&mut tape, i) = n;
            }
            MulAt(from, to, factor) => {
                let Some(from) = at(pointer, from) else { break };
                // With a 0 counter it adds nothing, wherever the target is. The loop
                // it came from wouldn't have run, so the target can even be off the tape.
                let counter = *cell(&mut tape, from);
                if counter != 0 {
                    let Some(to) = at(pointer, to) else { break };
                    let target = cell(&mut tape, to);
                    *target = target.wrapping_add(counter.wrapping_mul(factor));
                }
            }
            // Stopping partway through a scan is fine: resuming it carries on from
            // wherever the pointer got to.
            Scan(step) => loop {
                let Some(i) = at(pointer, 0) else { break 'run };
                if *cell(&mut tape, i) == 0 {
                    break;
                }
                if steps >= step_limit {
                    break 'run;
                }
                // Don't step onto a cell off the tape: the compiled scan takes that
                // step itself, which `--bounds abort` checks and `wrap` wraps.
                if at(pointer + step, 0).is_none() {
                    break 'run;
                }
                steps += 1;
                pointer += step;
            },
            Output(offset) => {
                let Some(i) = at(pointer, offset) else { break };
                output.push(*cell(&mut tape, i));
            }
            Input(_) => break,
            // A check that fails is left to the compiled program, which aborts.
            Check(min, max) => {
                if at(pointer, min).is_none() || at(pointer, max).is_none() {
                    break;
                }
            }
            // Jumping to the partner and then stepping past it lands after `]` for
            // `[`, and at the start of the body for `]`.
            JmpZ(_, offset) => {
                let Some(i) = at(pointer, offset) else { break };
                if *cell(&mut tape, i) == 0 {
                    index = partner[index];
                }
            }
            JmpNZ(_, offset) => {
                let Some(i) = at(pointer, offset) else { break };
                if *cell(&mut tape, i) != 0 {
                    index = partner[index];
                }
            }
        }

        index += 1;
    }

    let used = tape
        .iter()
        .rposition(|&c| c != 0)
        .map_or(0, |last| last + 1);
    tape.truncate(used);

    let resume = (index < tokens.len()).then_some(Resume {
        index,
        pointer,
        tape,
    });

    Evaluation { output, resume }
}

/// For each bracket, the index of its partner. Other tokens map to 0.
fn match_loops(tokens: &[Token]) -> Vec<usize> {
    let mut partner = vec![0; tokens.len()];
    let mut open = Vec::new();

    for (i, token) in tokens.iter().enumerate() {
        match token.kind() {
            TokenKind::JmpZ(..) => open.push(i),
            TokenKind::JmpNZ(..) => {
                let j = open.pop().expect("jumps are resolved");
                partner[i] = j;
                partner[j] = i;
            }
            _ => (),
        }
    }

    partner
}

#[cfg(test)]
mod tests;
