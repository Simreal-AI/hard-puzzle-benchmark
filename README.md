# Hard Puzzle Benchmark — topic package

749 answered puzzles are organized into 15 primary topics. Each topic has a JSONL and CSV file. Question images and explanation figures are in `assets/`; every row points to package-relative paths.

Use `manifest.json` for counts and file hashes, `scoring_config.json` for scoring, and `BENCHMARK_PROTOCOL.md` for the evaluation procedure. The answer-only core has 707 rows. The headline micro-average covers all 707 core rows in 15 topics. Topics with fewer than 20 core items are flagged as small samples but remain in the denominator. Report all topic accuracies with correct counts, denominators, and 95% Wilson intervals; the macro-average is diagnostic only.

During evaluation, show only `question` and its question-role assets to the solver. Keep `answer_only`, `explanation`, and explanation-role assets hidden until the final answer is locked. Answer-only items have a 30-minute limit; proof-certificate items have a 60-minute limit and a separate score.

To score a predictions JSONL file containing `id` and `final_answer`, run `python3 score_predictions.py --dataset . --predictions predictions.jsonl --output score_report.json`. Safe numeric and unit equivalence is handled automatically; uncertain semantic equivalence requires documented adjudication before publishing a final accuracy.
