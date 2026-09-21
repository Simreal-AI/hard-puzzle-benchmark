# Hard Puzzle Benchmark — final topic package

This package contains 751 answer-bearing puzzle records organized only by the canonical primary topic. Each topic has one JSONL file and one CSV file under `topics/`. Every row includes `question`, `answer_only`, and `explanation`, plus taxonomy, evaluation, source, and provenance metadata.

Start with `manifest.json` for counts and hashes, and `scoring_config.json` for topic denominators and timing. The 709-row answer-only core uses binary accuracy within each topic and a 30-minute per-item limit. The 18 proof-certificate rows use a 60-minute limit and remain a separate score.

The full topic files are reference/gold data. An evaluator must expose the question and packaged assets to the solver while keeping `answer_only` and `explanation` hidden until the final answer is locked.
