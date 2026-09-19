# Piano Arrangement Lab

Give it a chord chart. It gives you back something a person can actually play,
at the difficulty you ask for, and shows its working.

```
$ arrange "Dm7 G7 Cmaj7" --level beginner

BEGINNER  —  Root-position chords only, a single bass note in the left hand, at
most three notes in the right, nothing wider than an octave, no extensions and
nothing outside the two octaves above middle C.

  chord     left hand            right hand                     span   cost
  -------------------------------------------------------------------------
  Dm7       D3                   F4 C5 D5                          9   1.45
  G7        G2                   F4 G4 B4                          6   7.85
  Cmaj7     C3                   E4 B4 C5                          8   3.45

  total cost 12.75   hand travel 13 semitones   widest stretch 9 semitones
  92 transitions evaluated (exact, not greedy)

  voice-leading notes:
    G7: voice overlap — voice 4 falls to 71, below voice 3's 72
```

## The problem, and why it is not a lookup table

A chord symbol names pitch *classes*, never octaves. "Cmaj7" is four notes and
several hundred ways two hands can play them. Choosing well is not a matter of
looking each chord up, because the best voicing for a chord depends entirely on
the chord before it: a lovely Cmaj7 that leaves the hand a tenth away from the
next chord is the wrong Cmaj7.

Written out, that is a shortest-path problem. Each chord contributes a layer of
candidate voicings. Each candidate carries a **static cost** — how awkward it is
in isolation, from hand span, muddy low intervals, missing chord tones, register.
Each pair of candidates in adjacent layers carries a **transition cost** — the
part-writing rules broken between them, plus the physical distance the hands
travel, minus a discount for notes held in common.

The best arrangement is the cheapest path through that lattice. The Viterbi
recurrence finds it exactly in `O(n·k²)`, where the obvious alternative — try
every combination — is `O(kⁿ)`.

### Exactness is the point, and it is measured

A greedy pass (take the best chord, then its best follower, and so on) is what
an arranger written in an afternoon does. It cannot accept a slightly worse
voicing now to avoid a much worse one later, and on real music that costs it:

| level | optimal | greedy | greedy is worse by | strictly worse on | hand travel | rules broken |
|---|---|---|---|---|---|---|
| beginner | 254.7 | 268.1 | **5.3%** | 5/8 | 318 vs 336 | 4 vs 6 |
| intermediate | 75.3 | 82.6 | **9.6%** | 7/8 | 297 vs 304 | 0 vs 1 |
| advanced | 27.9 | 36.0 | **28.9%** | 6/8 | 305 vs 304 | 0 vs 1 |

Eight real progressions — a ii-V-I, Coltrane changes, Autumn Leaves, a twelve-bar
blues, Canon in D, a chromatic descent, a slash-bass line, I-V-vi-IV. Both
solvers are in the package (`arrange` and `arrange_greedy`) so the comparison is
reproducible rather than asserted.

`test_arrange.py` also checks the solver against **brute force** — every path
enumerated — on three-chord progressions at all three levels. The fast answer
and the exhaustive answer agree exactly.

## What "beginner" means, precisely

Difficulty is not an adjective here, it is a set of numbers the search must
respect: largest interval either hand spans, most notes per hand, which
registers, whether inversions and extensions are available. Stating them as
data is what makes them checkable — `test_difficulty.py` asserts that across
every progression, level and style, **no arrangement ever exceeds its own
limits**. A generator that merely aimed at easiness could not be tested that way.

When a chord cannot be played as written at a level, it is simplified and you
are told:

```
$ arrange "Cmaj9 G7/B" --level beginner
  simplified for this level:
    Cmaj9: dropped the 9th
    G7/B: played in root position instead of over the written bass
```

Silently playing a different chord would be the easy thing to do and the wrong
one.

## Styles

Five voicing styles, applied as *preferences*, never as constraints:

| style | what it does |
|---|---|
| `plain` | straight block chords |
| `jazzy` | colour tones preferred over plain ones, fifth free to drop — a shell voicing |
| `sparse` | as few notes as carry the harmony |
| `lush` | every available tone sounding, closely spaced |
| `hymn` | four-part chorale writing; parallel fifths punished hard |

A style can move the cost weights. It cannot touch the physical limits. Two
bugs made that rule worth stating in code rather than prose: asking for a
"jazzy" *beginner* arrangement once bought a fourth right-hand note, breaking
the one promise the difficulty level makes; and capping "sparse" at two
right-hand notes made `Dm7` unvoiceable, because its root, third and seventh
are three tones and none is optional. A preference expressed as cost degrades
gracefully where a hard cap fails.

## The AI layer, and the wall it sits behind

You can describe what you want instead of setting flags:

```
$ arrange "Dm7 G7 Cmaj7 A7" --describe "a gentle jazzy version, slow"
read "a gentle jazzy version, slow" as: intermediate, jazzy, 66 bpm  [keywords]
```

**This works with no API key.** Most of what people type is keyword-shaped, and
a deterministic parser handles it — including which word wins when two conflict,
resolved by position in the sentence rather than by dictionary order.

A language model is optional, and its job is deliberately tiny: read a sentence
and fill in four fields — level, style, bpm, beats per chord — each validated
against an enumeration or a numeric range before the engine sees it. **The model
never chooses a note.** That is what makes the feature safe to expose publicly:
the worst a bad completion can do is fail validation and fall back.

```bash
export GROQ_API_KEY=...        # free tier, self-serve
arrange "Dm7 G7 Cmaj7" --describe "like someone who's been playing 30 years" --provider groq
```

Four providers: `anthropic`, `groq`, `gemini`, `ollama`. Groq and Gemini issue
free keys to anyone; Ollama needs none but only runs locally. The spread exists
because of a real constraint — a static site cannot hold a secret, so a visitor
either brings their own key or takes the deterministic path, and a visitor who
brings one will not be bringing an Anthropic key specifically.

Anything the parser cannot account for is reported rather than dropped:

```
$ arrange "C Am" --describe "make it sound like Debussy underwater"
  (not understood, and ignored: 'debussy underwater')
```

Being told a request was half-ignored is worth more than a confident answer to
a different question.

## Output

Two-track MIDI, left hand and right hand on separate tracks so they land on
separate staves when imported:

```bash
arrange "Dm7 G7 Cmaj7" --midi out.mid --bpm 120
```

The writer is 80 lines of `struct.pack` against the Standard MIDI File spec,
with no dependency. `test_midi.py` parses its own output back — the header's
declared track count against the file's actual chunks, every note-on matched by
a note-off, the written pitches against the arranged ones. An early version
omitted the four-byte length field from the header chunk, producing a file that
was the right size and unreadable by anything; no test of "did it write some
bytes" would have caught it.

## Install and use

No runtime dependencies. The engine is integer arithmetic over pitch classes
and a dynamic program over a few thousand states.

```bash
pip install -e ".[dev]"      # add [llm] for the optional model layer
pytest -q                    # 516 tests

arrange "C Am F G7"
arrange "Dm7 G7 Cmaj7" --level advanced --style jazzy
arrange "C G Am F" --compare              # all three levels side by side
arrange "C G Am F" --greedy               # the baseline, for comparison
```

```python
from arranger.arrange import arrange

result = arrange("Dm7 G7 Cmaj7", level="intermediate", style="jazzy")
for step in result.steps:
    print(step.chord.symbol, step.voicing.left, step.voicing.right)
print(result.total_cost, result.total_motion, result.violations)
```

## Performance

The candidate cap is the dial between quality and speed, and it is set from a
measurement rather than a guess. Across the corpus at three levels and five
styles — 120 arrangements — a cap of **60 produces identical results to a cap of
200, seven times faster**. It degrades below 40: at 25 it costs 0.08% and is
worse on 8 of the 120; at 8 it costs 3.3%. `test_arrange.py` re-checks that
raising the cap finds nothing better, so lowering it carelessly fails the suite
instead of quietly producing worse arrangements.

Two other measured changes, both from profiling rather than intuition: caching
`Voicing.pitches` (3.7 million calls, each re-sorting the same five integers)
and computing rule penalties without allocating the explanation objects. At the
original cap of 160 those two together took a seven-chord advanced arrangement
from 2.18s to 0.44s; with the cap at 60 as well it is **0.070s**, and the test
suite went from 109s to 27s. The allocating version is kept as `explain()` for
reporting, and a test asserts the two agree on every pair in the corpus.

## Layout

```
src/arranger/
  theory.py        pitches, intervals, the chord-symbol parser
  difficulty.py    what beginner/intermediate/advanced mean, as numbers
  voicing.py       candidate voicings for one chord, and the static cost
  voiceleading.py  the part-writing rules, and the transition cost
  arrange.py       the Viterbi solver, and the greedy baseline it beats
  intent.py        plain English to settings, without a model
  llm.py           plain English to settings, with one — behind a validator
  midi.py          Standard MIDI File output
  cli.py           the command line above
```

## Notes and limits

- **It arranges harmony, not music.** The input is a chord chart, so there is
  no melody to voice around and nothing decides which note is on top for
  melodic reasons. A real arranger starts from the tune.
- **There is no rhythm.** Every chord is held for the same `--beats` (2.0 by
  default), struck together and released together. The MIDI is a harmonic
  sketch you can play or import, not a performance.
- **No dynamics, pedal or articulation.** Velocity is fixed per hand — 70 left,
  85 right, so the melody-side reads slightly louder — and that is the whole of
  the expressive content.
- **The cost weights are hand-set, not learned.** They encode ordinary
  part-writing practice and they are internally consistent, but nothing here
  has been fitted to, or validated against, what human arrangers actually
  choose. "Optimal" means cheapest under *these* weights. That the search finds
  the true minimum is proven against brute force; that the minimum is the
  *musical* answer is a claim this project does not make.
- **The greedy comparison is eight progressions.** Enough to show the gap is
  real and consistent in sign, not enough to put a confidence interval on
  "28.9% worse at advanced".
- **The candidate cap is measured on this corpus.** 60 matches 200 exactly
  across the 120 arrangements tested; a progression unlike anything in the
  corpus could in principle need more, and the test that catches that only
  covers the corpus.
- **Chord symbols only, and a fixed vocabulary of them.** The parser handles
  triads, sevenths, extensions, alterations and slash bass. Anything it cannot
  read is refused rather than approximated — see `theory.py` for what is in.
- **The model layer is optional and cannot widen the limits.** Without a key,
  `intent.py` reads the same sentences by keyword. With one, `llm.py` maps
  free text to the *same* settings object and a validator rejects anything out
  of range, so a model cannot talk the arranger past a difficulty constraint.
