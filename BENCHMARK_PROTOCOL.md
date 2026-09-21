# Hard Puzzle Benchmark protocol

## Official score

The official leaderboard population is the answer-only benchmark core. Each
eligible item receives binary credit: 1 for a correct final answer and 0 for an
incorrect, incomplete, malformed, abstained, or timed-out answer. Explanations
are retained for audit and error analysis but do not create partial credit.

For each canonical `domain_primary` topic:

```text
topic_accuracy = correct eligible items / all eligible items
```

Every eligible item is counted in exactly one primary topic. The official
overall score is the unweighted macro-average of all non-empty topic
accuracies. A micro-average should also be reported as a diagnostic, but it is
not the headline score because the topic sizes are intentionally uneven.

The current macro leaderboard is **provisional** until every topic contains at
least 20 eligible core items. Topics below that threshold still receive their
own accuracy, numerator, denominator, and confidence interval, but a single
item should not yet be allowed to determine a full 1/15 of a production
leaderboard score.

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
hardware/runtime environment, prompt template, dataset manifest SHA-256, and
both per-topic numerators and denominators. Evaluators must not expose
`answer_only` or `explanation` to the solver before the final answer is locked.
