# Hard Puzzle Benchmark — topic package

[![Status: public preview](https://img.shields.io/badge/status-public%20preview-34d399)](https://github.com/Simreal-AI)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

> **Public preview.** This package is an early, minimal release of the SimReal Hard Puzzle Benchmark: the answered puzzle set, the evaluation protocol and a scorer. Items, topics and scoring will change as the benchmark matures.
>
> Evaluations and partner access: [business@simreal.co](mailto:business@simreal.co) · All SimReal previews: [github.com/Simreal-AI](https://github.com/Simreal-AI)

749 answered puzzles are organized into 15 primary topics. Each topic has a JSONL and CSV file. Question images and explanation figures are in `assets/`; every row points to package-relative paths.

Use `manifest.json` for counts and file hashes, `scoring_config.json` for scoring, and `BENCHMARK_PROTOCOL.md` for the evaluation procedure. The answer-only core has 707 rows. The headline micro-average covers all 707 core rows in 15 topics. Topics with fewer than 20 core items are flagged as small samples but remain in the denominator. Report all topic accuracies with correct counts, denominators, and 95% Wilson intervals; the macro-average is diagnostic only.

During evaluation, show only `question` and its question-role assets to the solver. Keep `answer_only`, `explanation`, and explanation-role assets hidden until the final answer is locked. Answer-only items have a 30-minute limit; proof-certificate items have a 60-minute limit and a separate score.

To score a predictions JSONL file containing `id` and `final_answer`, run `python3 score_predictions.py --dataset . --predictions predictions.jsonl --output score_report.json`. Safe numeric and unit equivalence is handled automatically; uncertain semantic equivalence requires documented adjudication before publishing a final accuracy.

## Part of SimReal

This repository is one public preview in the [SimReal](https://simreal.co) product line: environments where AI agents act and real outcomes decide the score. See every preview at [github.com/Simreal-AI](https://github.com/Simreal-AI).

## License

Copyright 2026 Simreal-AI. Licensed under the [Apache License 2.0](LICENSE); see [`NOTICE`](NOTICE).
