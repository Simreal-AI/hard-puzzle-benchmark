# Hard Puzzle Benchmark protocol

## Official score

The official leaderboard population is the answer-only benchmark core. Each
eligible item receives binary credit: 1 for a correct final answer and 0 for an
incorrect, incomplete, abstained, or timed-out answer. Format-only differences
that cannot be safely normalized are queued for adjudication before a final
score is published. Explanations are retained for audit and error analysis but
do not create partial credit.

For a puzzle with more than one documented valid answer, encode every accepted
answer in the private reference. For an open-ended construction or optimization
puzzle, the published example need not be unique or optimal; a different
submission requires a task-specific check or documented adjudication. Do not
mark it wrong merely because its text differs from the example.
Rows tagged `answer_kind=constructive_witness` or
`reference_is_example_not_optimum=true` therefore enter verification when a
submitted answer differs, even when both answers are numeric.
When a reference is explicitly rounded to a required decimal precision, the
row's `evaluation.reference_rounded_decimal_places` records that precision as
an integer from 1 to 20. Compatible numeric answers within half a unit in the
last declared decimal place receive credit, including more precise answers;
the scorer never infers rounding tolerance from an unmarked plain decimal.
Unsupported symbolic forms remain pending for adjudication.

For each canonical `domain_primary` topic:

```text
topic_accuracy = correct eligible items / all eligible items
```

Every eligible item is counted in exactly one primary topic. The official
headline score is the micro-average over **all** answer-only core items:

```text
headline_score = correct answer-only core items /
                 all answer-only core items
```

The current package's exact row and core counts are recorded in `manifest.json`.
Every answer-only core item contributes to the headline denominator across all
15 topics.
Report each topic's correct count, denominator, and 95% Wilson confidence
interval. Flag topics with fewer than 20 core items as small samples; the flag
does not remove their items from the headline. Report the unweighted
macro-average as a diagnostic only.

Historical difficulty candidates and proof-certificate rows are reported in
separate tracks and never change the official answer-only score.

## Time limits

- Answer-only core and historical-pilot item: **30 minutes per item**.
- Proof-certificate item: **60 minutes per item**.

The clock starts after the full prompt and any packaged assets are available
and stops when the evaluator receives the final answer. Tool setup, retries,
and self-correction occur inside the same limit. Run one independent attempt
per item. A timeout scores 0.

Keep these limits fixed across topics for comparability. After the first
strong-model pilot, calibrate the item pool rather than changing time by topic:
remove or demote ambiguous items, and target a useful accuracy band without
making easier topics artificially faster.

## Reproducibility requirements

Report the model and exact version, inference settings, tool/network policy,
hardware/runtime environment, prompt template, dataset manifest SHA-256,
headline numerator and denominator, and per-topic numerators and denominators.
Evaluators must not expose `answer_only`, `explanation`, or explanation-role
assets to the solver before the final answer is locked. Use the answer-blind
question split for solver input and keep the gold split separate. Because the
underlying puzzles are public, this split prevents local answer leakage but
does not establish that a model has never seen a puzzle during training.
