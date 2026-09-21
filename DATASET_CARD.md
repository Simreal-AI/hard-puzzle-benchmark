# Dataset card

## Contents

- Rows: 751
- Primary topics: 15
- Official answer-only core: 709
- Historical answer-only candidates: 24
- Proof-certificate rows: 18
- Required content per row: question, answer_only, explanation

## Source composition

- AlphaGeometry JGEX proof certificates: 18
- Dudeney Public Domain Puzzles: 14
- HARP: 390
- Jane Street Monthly Puzzles: 147
- Lewis Carroll — A Tangled Tale: 10
- PuzzleWorld: 172

## Organization

`domain_primary` determines the single topic file for each record. Secondary domains and reasoning skills stay in the row and do not duplicate the record across files. Source and rights objects remain as row-level provenance fields.

## Scoring

Report binary accuracy for every primary topic. The provisional overall score is the unweighted macro-average of the 15 topic accuracies. Timeouts, abstentions, and invalid final-answer formats score zero. See `scoring_config.json`.
