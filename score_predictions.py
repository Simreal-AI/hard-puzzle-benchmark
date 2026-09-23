#!/usr/bin/env python3
"""Score answer-only topic predictions from the final JSONL package.

Usage:
    python3 scripts/score_topic_predictions.py \
      --dataset outputs/hard_puzzle_benchmark_topic_final \
      --predictions predictions.jsonl --output score_report.json \
      --review-queue private_review_queue.jsonl

Predictions contain ``id`` and either ``final_answer`` or ``answer``. Optional
``elapsed_minutes`` and ``status`` fields enforce the published per-item limit.
Missing predictions, abstentions, malformed answers, and timeouts score zero.
Unresolved semantic equivalence is pending adjudication, never silently scored
wrong. The optional review queue contains gold answers and must remain private.
Proof-certificate submissions require a separate proof verifier.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any


SMALL_TOPIC_N = 20
WILSON_Z_95 = 1.959963984540054
ZERO_STATUSES = {"timeout", "timed_out", "abstain", "abstained", "invalid", "error"}
SUCCESS_STATUSES = {"completed", "complete", "submitted", "answered", "ok", "success"}
NUMBER_TOKEN = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
LATEX_FRAC = re.compile(r"\\(?:dfrac|tfrac|frac)")
LATEX_SQRT = re.compile(r"\\sqrt")
UNIT_FACTORS = {
    "mm": ("length", Fraction(1, 1000)), "millimeter": ("length", Fraction(1, 1000)),
    "millimeters": ("length", Fraction(1, 1000)), "cm": ("length", Fraction(1, 100)),
    "centimeter": ("length", Fraction(1, 100)), "centimeters": ("length", Fraction(1, 100)),
    "m": ("length", Fraction(1)), "meter": ("length", Fraction(1)),
    "meters": ("length", Fraction(1)), "km": ("length", Fraction(1000)),
    "kilometer": ("length", Fraction(1000)), "kilometers": ("length", Fraction(1000)),
    "s": ("time", Fraction(1)), "sec": ("time", Fraction(1)),
    "second": ("time", Fraction(1)), "seconds": ("time", Fraction(1)),
    "min": ("time", Fraction(60)), "minute": ("time", Fraction(60)),
    "minutes": ("time", Fraction(60)), "h": ("time", Fraction(3600)),
    "hr": ("time", Fraction(3600)), "hour": ("time", Fraction(3600)),
    "hours": ("time", Fraction(3600)), "day": ("time", Fraction(86400)),
    "days": ("time", Fraction(86400)),
    "mg": ("mass", Fraction(1, 1000)), "g": ("mass", Fraction(1)),
    "gram": ("mass", Fraction(1)), "grams": ("mass", Fraction(1)),
    "kg": ("mass", Fraction(1000)), "kilogram": ("mass", Fraction(1000)),
    "kilograms": ("mass", Fraction(1000)),
    "ml": ("volume", Fraction(1, 1000)), "l": ("volume", Fraction(1)),
    "liter": ("volume", Fraction(1)), "liters": ("volume", Fraction(1)),
}


def _unwrap_braced(command: str, value: str) -> str:
    """Unwrap a full-string LaTeX command with balanced outer braces."""
    prefix = command + "{"
    if not value.startswith(prefix) or not value.endswith("}"):
        return value
    depth = 0
    for index in range(len(command), len(value)):
        character = value[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0 and index != len(value) - 1:
                return value
        if depth < 0:
            return value
    return value[len(prefix):-1] if depth == 0 else value


def normalize_answer(value: str) -> str:
    """Conservative, deterministic text matching; not a semantic prose grader."""
    answer = unicodedata.normalize("NFKC", value).strip()
    answer = answer.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "−": "-"}))
    # Common publication wrappers are formatting, not answer content.
    for _ in range(4):
        previous = answer
        for opening, closing in (("$$", "$$"), ("$", "$"), (r"\(", r"\)"), (r"\[", r"\]")):
            if answer.startswith(opening) and answer.endswith(closing) and len(answer) > len(opening) + len(closing):
                answer = answer[len(opening):-len(closing)].strip()
                break
        answer = _unwrap_braced(r"\boxed", answer)
        if answer == previous:
            break
    answer = answer.replace(r"\left", "").replace(r"\right", "")
    answer = " ".join(answer.split()).casefold()
    # Remove commas only when the entire answer is a conventional number.
    if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", answer):
        answer = answer.replace(",", "")
    return answer


def _braced_group(value: str, start: int) -> tuple[str, int] | None:
    if start >= len(value) or value[start] != "{":
        return None
    depth = 0
    for index in range(start, len(value)):
        if value[index] == "{":
            depth += 1
        elif value[index] == "}":
            depth -= 1
            if depth == 0:
                return value[start + 1:index], index + 1
    return None


def _plain_math(value: str) -> str | None:
    """Translate a small, auditable subset of LaTeX into arithmetic syntax."""
    output: list[str] = []
    index = 0
    while index < len(value):
        match = LATEX_FRAC.match(value, index)
        if match:
            numerator = _braced_group(value, match.end())
            denominator = _braced_group(value, numerator[1]) if numerator else None
            if not numerator or not denominator:
                return None
            top = _plain_math(numerator[0])
            bottom = _plain_math(denominator[0])
            if top is None or bottom is None:
                return None
            output.append(f"(({top})/({bottom}))")
            index = denominator[1]
            continue
        match = LATEX_SQRT.match(value, index)
        if match:
            radicand = _braced_group(value, match.end())
            if not radicand:
                return None
            inner = _plain_math(radicand[0])
            if inner is None:
                return None
            output.append(f"sqrt({inner})")
            index = radicand[1]
            continue
        replacement = None
        for original, converted in ((r"\cdot", "*"), (r"\times", "*"), (r"\div", "/")):
            if value.startswith(original, index):
                replacement = (converted, len(original))
                break
        if replacement:
            output.append(replacement[0])
            index += replacement[1]
            continue
        character = value[index]
        output.append({"{": "(", "}": ")", "×": "*", "÷": "/", "−": "-"}.get(character, character))
        index += 1
    return "".join(output)


class _RationalParser:
    """Bounded rational arithmetic; never eval arbitrary Python or symbolic text."""

    def __init__(self, value: str) -> None:
        self.tokens: list[str] = []
        index = 0
        while index < len(value):
            if value[index].isspace():
                index += 1
                continue
            match = NUMBER_TOKEN.match(value, index)
            if match:
                self.tokens.append(match.group())
                index = match.end()
            elif value.startswith("sqrt", index):
                self.tokens.append("sqrt")
                index += 4
            elif value[index] in "+-*/^()":
                self.tokens.append(value[index])
                index += 1
            else:
                raise ValueError("unsupported arithmetic token")
        if not self.tokens or len(self.tokens) > 100:
            raise ValueError("empty or oversized arithmetic expression")
        self.index = 0

    def _take(self, token: str) -> bool:
        if self.index < len(self.tokens) and self.tokens[self.index] == token:
            self.index += 1
            return True
        return False

    def _checked(self, value: Fraction) -> Fraction:
        if value.numerator.bit_length() > 512 or value.denominator.bit_length() > 512:
            raise ValueError("arithmetic expression is too large")
        return value

    def parse(self) -> Fraction:
        result = self._expression()
        if self.index != len(self.tokens):
            raise ValueError("trailing arithmetic tokens")
        return result

    def _expression(self) -> Fraction:
        result = self._term()
        while self.index < len(self.tokens) and self.tokens[self.index] in {"+", "-"}:
            operator = self.tokens[self.index]
            self.index += 1
            right = self._term()
            result = self._checked(result + right if operator == "+" else result - right)
        return result

    def _term(self) -> Fraction:
        result = self._unary()
        while self.index < len(self.tokens) and self.tokens[self.index] in {"*", "/"}:
            operator = self.tokens[self.index]
            self.index += 1
            right = self._unary()
            if operator == "/" and right == 0:
                raise ValueError("division by zero")
            result = self._checked(result * right if operator == "*" else result / right)
        return result

    def _unary(self) -> Fraction:
        if self._take("+"):
            return self._unary()
        if self._take("-"):
            return -self._unary()
        result = self._atom()
        if self._take("^"):
            exponent = self._unary()
            if exponent.denominator != 1 or abs(exponent.numerator) > 12:
                raise ValueError("unsupported exponent")
            result = self._checked(result ** exponent.numerator)
        return result

    def _atom(self) -> Fraction:
        if self._take("("):
            result = self._expression()
            if not self._take(")"):
                raise ValueError("unbalanced parentheses")
            return result
        if self._take("sqrt"):
            if not self._take("("):
                raise ValueError("sqrt needs parentheses")
            radicand = self._expression()
            if not self._take(")") or radicand < 0:
                raise ValueError("invalid square root")
            numerator = math.isqrt(radicand.numerator)
            denominator = math.isqrt(radicand.denominator)
            if numerator * numerator != radicand.numerator or denominator * denominator != radicand.denominator:
                raise ValueError("non-rational square root")
            return Fraction(numerator, denominator)
        if self.index >= len(self.tokens):
            raise ValueError("missing number")
        token = self.tokens[self.index]
        if not NUMBER_TOKEN.fullmatch(token) or len(token) > 32:
            raise ValueError("unsupported number")
        self.index += 1
        try:
            decimal = Decimal(token)
            if not decimal.is_finite() or abs(decimal.adjusted()) > 24:
                raise ValueError("number magnitude is too large")
            return self._checked(Fraction(decimal))
        except InvalidOperation as error:
            raise ValueError("invalid decimal") from error


@dataclass(frozen=True)
class Quantity:
    value: Fraction
    dimension: str | None
    approximate: bool
    rounding_tolerance: Fraction | None
    decimal_places: int


def _decimal_precision(value: str) -> tuple[Fraction | None, int]:
    match = re.fullmatch(r"[+-]?(?:\d+)?\.(\d+)(?:e([+-]?\d+))?", value, re.IGNORECASE)
    if not match:
        return None, 0
    places = len(match.group(1))
    exponent = int(match.group(2) or "0")
    if places > 20 or abs(exponent) > 20:
        return None, 0
    step_power = exponent - places
    step = Fraction(10 ** step_power) if step_power >= 0 else Fraction(1, 10 ** -step_power)
    return step / 2, places


def parse_quantity(value: str) -> Quantity | None:
    text = normalize_answer(value).strip()
    if not text or len(text) > 200:
        return None
    approximate = bool(re.search(r"≈|\\approx|\.\.\.|…|^~|^about\b|^approximately\b", text))
    text = re.sub(r"^(?:about|approximately)\s+", "", text)
    text = text.replace(r"\approx", "≈").lstrip("≈~ ").rstrip("… ")
    if text.endswith("..."):
        text = text[:-3].rstrip()
    if text.endswith("%"):
        percent = True
        text = text[:-1].strip()
    else:
        percent = False
    dimension = None
    factor = Fraction(1, 100) if percent else Fraction(1)
    if not percent:
        text = re.sub(r"\\(?:mathrm|text)\{([a-z]+)\}", r"\1", text)
        unit_match = re.fullmatch(r"(.+?)\s*([a-z]+)", text)
        if unit_match and unit_match.group(2) in UNIT_FACTORS:
            text = unit_match.group(1).strip()
            dimension, unit_factor = UNIT_FACTORS[unit_match.group(2)]
            factor *= unit_factor
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    converted = _plain_math(text)
    if converted is None:
        return None
    try:
        result = _RationalParser(converted).parse() * factor
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    tolerance, places = _decimal_precision(text)
    return Quantity(result, dimension, approximate, tolerance * factor if tolerance else None, places)


def _scalar_match(answer: str, reference: str) -> tuple[int | None, str]:
    if normalize_answer(answer) == normalize_answer(reference):
        return 1, "correct_exact"
    predicted = parse_quantity(answer)
    gold = parse_quantity(reference)
    if predicted is None or gold is None or predicted.dimension != gold.dimension:
        return None, "pending_semantic_adjudication"
    if predicted.value == gold.value:
        return 1, "correct_numeric_equivalence"
    difference = abs(predicted.value - gold.value)
    if gold.approximate and gold.rounding_tolerance is not None and difference <= gold.rounding_tolerance:
        return 1, "correct_published_numeric_precision"
    # An exact rational answer can be represented by a sufficiently precise
    # decimal approximation; shorter rounded submissions need adjudication.
    if predicted.rounding_tolerance is not None:
        if difference <= predicted.rounding_tolerance:
            if predicted.decimal_places >= 5:
                return 1, "correct_numeric_rounding"
            return None, "pending_numeric_precision_adjudication"
    if gold.approximate or predicted.approximate:
        return None, "pending_numeric_precision_adjudication"
    return 0, "incorrect_numeric"


def _split_top_level(value: str, separator: str) -> list[str] | None:
    parts = []
    depth = 0
    start = 0
    for index, character in enumerate(value):
        if character in "({[":
            depth += 1
        elif character in ")}]":
            depth -= 1
            if depth < 0:
                return None
        elif character == separator and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    if depth != 0:
        return None
    parts.append(value[start:].strip())
    return parts if all(parts) else None


def _set_parts(value: str, force: bool = False) -> list[str] | None:
    text = normalize_answer(value)
    if text.startswith(r"\{") and text.endswith(r"\}"):
        text = text[2:-2]
    elif text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    elif not force:
        return None
    parts = _split_top_level(text, ",")
    return parts if parts and len(parts) > 1 else None


def _assignment_parts(value: str) -> dict[str, str] | None:
    parts = _split_top_level(normalize_answer(value), ";")
    if not parts:
        return None
    parsed = {}
    for part in parts:
        match = re.fullmatch(r"([a-z][a-z0-9_ ()]*?)\s*(=|≈)\s*(.+)", part)
        if not match:
            return None
        label = " ".join(match.group(1).split())
        if label in parsed:
            return None
        numeric = match.group(3)
        parsed[label] = ("≈" if match.group(2) == "≈" else "") + numeric
    return parsed


def compare_answer(answer: str, reference: str, evaluation: dict[str, Any] | None = None) -> tuple[int | None, str]:
    """Return definite credit or a pending result for semantic review."""
    evaluation = evaluation or {}
    if normalize_answer(answer) == normalize_answer(reference):
        return 1, "correct_exact"
    if (evaluation.get("reference_is_example_not_optimum") is True
            or evaluation.get("answer_kind") == "constructive_witness"):
        # The gold is a verified example, not a uniqueness or optimality proof.
        # A different construction or even a higher score must be checked
        # against the puzzle constraints before assigning binary credit.
        return None, "pending_constructive_witness_verification"
    rounded_places = evaluation.get("reference_rounded_decimal_places")
    if rounded_places is not None:
        if isinstance(rounded_places, bool) or not isinstance(rounded_places, int) or not 1 <= rounded_places <= 20:
            raise ValueError("reference_rounded_decimal_places must be an integer from 1 to 20")
        gold = parse_quantity(reference)
        if gold is None or gold.decimal_places != rounded_places or gold.rounding_tolerance is None:
            raise ValueError("rounded numeric reference does not match its declared decimal places")
        predicted = parse_quantity(answer)
        if predicted is None or predicted.dimension != gold.dimension:
            return None, "pending_semantic_adjudication"
        if abs(predicted.value - gold.value) <= gold.rounding_tolerance:
            return 1, "correct_reference_rounding"
        return 0, "incorrect_numeric"
    if evaluation.get("answer_kind") == "exact_text":
        return 0, "incorrect_exact_text"
    reference_set = _set_parts(reference, evaluation.get("answer_kind") == "unordered_set")
    answer_set = _set_parts(answer, evaluation.get("answer_kind") == "unordered_set")
    if reference_set is not None and answer_set is not None and len(reference_set) == len(answer_set):
        remaining = answer_set.copy()
        for gold_part in reference_set:
            match_index = next((index for index, candidate in enumerate(remaining)
                                if _scalar_match(candidate, gold_part)[0] == 1), None)
            if match_index is None:
                break
            remaining.pop(match_index)
        else:
            return 1, "correct_unordered_set"
        return None, "pending_set_adjudication"
    gold_assignments = _assignment_parts(reference)
    predicted_assignments = _assignment_parts(answer)
    if gold_assignments and predicted_assignments and gold_assignments.keys() == predicted_assignments.keys():
        decisions = [_scalar_match(predicted_assignments[key], gold_assignments[key])[0] for key in gold_assignments]
        if all(decision == 1 for decision in decisions):
            return 1, "correct_labeled_components"
        if any(decision is None for decision in decisions):
            return None, "pending_component_adjudication"
        return 0, "incorrect_labeled_numeric_components"
    if gold_assignments and len(gold_assignments) == 1 and not predicted_assignments:
        only_value = next(iter(gold_assignments.values()))
        return _scalar_match(answer, only_value)
    return _scalar_match(answer, reference)


def wilson_95(correct: int, n: int) -> dict[str, float] | None:
    if n == 0:
        return None
    p = correct / n
    z2 = WILSON_Z_95 ** 2
    denominator = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denominator
    half_width = WILSON_Z_95 * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n) / denominator
    return {"low": max(0.0, center - half_width), "high": min(1.0, center + half_width)}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{number}: invalid JSON: {error}") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{number}: expected a JSON object")
            rows.append(row)
    return rows


def load_dataset(dataset: Path) -> dict[str, dict[str, Any]]:
    if dataset.is_file() and dataset.suffix == ".jsonl":
        files = [dataset]
    elif dataset.is_dir():
        topic_dir = dataset / "topics" if (dataset / "topics").is_dir() else dataset
        files = sorted(topic_dir.glob("*.jsonl"))
    else:
        raise ValueError(f"dataset must be a topic directory or JSONL file: {dataset}")
    if not files:
        raise ValueError(f"no topic JSONL files found in {dataset}")
    rows = {}
    for path in files:
        for row in read_jsonl(path):
            item_id = row.get("id")
            if not isinstance(item_id, str) or not item_id:
                raise ValueError(f"{path}: dataset row has no string id")
            if item_id in rows:
                raise ValueError(f"duplicate dataset id: {item_id}")
            if not isinstance(row.get("domain_primary"), str) or not row["domain_primary"]:
                raise ValueError(f"{path}: row {item_id} has no primary topic")
            rows[item_id] = row
    return rows


def load_predictions(path: Path, known_ids: set[str]) -> dict[str, dict[str, Any]]:
    predictions = {}
    for row in read_jsonl(path):
        item_id = row.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("prediction has no string id")
        if item_id not in known_ids:
            raise ValueError(f"prediction id is absent from dataset: {item_id}")
        if item_id in predictions:
            raise ValueError(f"duplicate prediction id: {item_id}")
        if "final_answer" in row and "answer" in row and row["final_answer"] != row["answer"]:
            raise ValueError(f"conflicting answer fields for {item_id}")
        if "elapsed_minutes" in row and row["elapsed_minutes"] is not None:
            elapsed = row["elapsed_minutes"]
            if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError(f"elapsed_minutes must be a nonnegative finite number for {item_id}")
        if "status" in row and row["status"] is not None:
            status = row["status"]
            if not isinstance(status, str) or status.strip().casefold() not in ZERO_STATUSES | SUCCESS_STATUSES:
                raise ValueError(f"unrecognized status for {item_id}: {status!r}")
        predictions[item_id] = row
    return predictions


def load_adjudications(path: Path, known_ids: set[str]) -> dict[str, dict[str, str]]:
    """Load explicit, auditable decisions for uncertain answer equivalence."""
    adjudications: dict[str, dict[str, str]] = {}
    for row in read_jsonl(path):
        item_id = row.get("id")
        if not isinstance(item_id, str) or item_id not in known_ids:
            raise ValueError(f"adjudication id is absent from dataset: {item_id!r}")
        if item_id in adjudications:
            raise ValueError(f"duplicate adjudication id: {item_id}")
        if row.get("decision") not in {"correct", "incorrect"}:
            raise ValueError(f"adjudication decision must be correct or incorrect for {item_id}")
        reviewer_type = row.get("reviewer_type")
        if reviewer_type not in {"human", "codex_ai"}:
            raise ValueError(f"reviewer_type must be human or codex_ai for {item_id}")
        if reviewer_type == "human" and (not isinstance(row.get("reviewer_id"), str) or not row["reviewer_id"].strip()):
            raise ValueError(f"human adjudication requires reviewer_id for {item_id}")
        rationale = row.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f"adjudication requires nonempty rationale for {item_id}")
        adjudications[item_id] = {
            "decision": row["decision"], "reviewer_type": reviewer_type,
            "reviewer_id": row.get("reviewer_id", ""), "rationale": rationale,
        }
    return adjudications


def item_result(
    item: dict[str, Any], prediction: dict[str, Any] | None,
    adjudication: dict[str, str] | None = None,
) -> tuple[int | None, str]:
    """Return definite credit, or None when equivalence/proof is unresolved."""
    evaluation = item.get("evaluation") or {}
    is_proof = evaluation.get("track") == "proof_certificate" or evaluation.get("scoring_requires_proof") is True
    limit = 60 if is_proof else 30
    if prediction is None:
        return 0, "missing_prediction"
    status = prediction.get("status")
    if isinstance(status, str) and status.strip().casefold() in ZERO_STATUSES:
        return 0, status.strip().casefold()
    elapsed = prediction.get("elapsed_minutes")
    if elapsed is not None and elapsed > limit:
        return 0, "timeout"
    answer = prediction.get("final_answer", prediction.get("answer"))
    if answer is None or (isinstance(answer, str) and not answer.strip()):
        return 0, "abstained"
    if not isinstance(answer, str):
        return 0, "invalid_answer_format"
    if is_proof:
        return None, "requires_proof_verifier"
    reference = item.get("answer_only")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError(f"dataset item {item['id']} has no string answer_only")
    references = [reference]
    accepted = evaluation.get("accepted_answers")
    if accepted is not None:
        if not isinstance(accepted, list) or not all(isinstance(value, str) and value.strip() for value in accepted):
            raise ValueError(f"dataset item {item['id']} has invalid accepted_answers")
        references.extend(accepted)
    decisions = [compare_answer(answer, gold, evaluation) for gold in references]
    match = next((decision for decision in decisions if decision[0] == 1), None)
    if match:
        return match
    if all(decision[0] == 0 for decision in decisions):
        return decisions[0]
    if adjudication is not None:
        credit = 1 if adjudication["decision"] == "correct" else 0
        return credit, f"adjudicated_{adjudication['decision']}_{adjudication['reviewer_type']}"
    return None, next(decision[1] for decision in decisions if decision[0] is None)


def score(
    dataset: dict[str, dict[str, Any]], predictions: dict[str, dict[str, Any]],
    adjudications: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    adjudications = adjudications or {}
    topic_items: dict[str, list[tuple[dict[str, Any], int | None, str]]] = defaultdict(list)
    other_tracks: dict[str, list[tuple[int | None, str]]] = defaultdict(list)
    outcome_counts: dict[str, int] = defaultdict(int)
    applied_adjudications: dict[str, int] = defaultdict(int)
    pending_item_ids: list[str] = []
    for item_id, item in dataset.items():
        original_credit, _ = item_result(item, predictions.get(item_id))
        adjudication = adjudications.get(item_id)
        if adjudication is not None and original_credit is not None:
            raise ValueError(f"adjudication is only permitted for pending answer-only items: {item_id}")
        credit, reason = item_result(item, predictions.get(item_id), adjudication)
        if adjudication is not None:
            if reason == "requires_proof_verifier":
                raise ValueError(f"proof item requires a proof verifier, not answer adjudication: {item_id}")
            applied_adjudications[adjudication["reviewer_type"]] += 1
        elif credit is None and reason != "requires_proof_verifier":
            pending_item_ids.append(item_id)
        outcome_counts[reason] += 1
        evaluation = item.get("evaluation") or {}
        if evaluation.get("benchmark_core") is True and evaluation.get("counts_toward_official_topic_score", True) is True:
            if evaluation.get("track") == "proof_certificate":
                raise ValueError(f"proof item incorrectly marked as answer-only core: {item_id}")
            topic_items[item["domain_primary"]].append((item, credit, reason))
        else:
            track = evaluation.get("track") or "other_noncore"
            other_tracks[track].append((credit, reason))

    topic_reports = []
    for topic in sorted({item["domain_primary"] for item in dataset.values()}):
        entries = topic_items.get(topic, [])
        n = len(entries)
        correct = sum(credit == 1 for _, credit, _ in entries)
        pending = sum(credit is None for _, credit, _ in entries)
        included = n > 0
        topic_reports.append({
            "topic": topic,
            "correct": correct,
            "n": n,
            "pending_adjudication": pending,
            "accuracy": correct / n if n and not pending else None,
            "accuracy_bounds": {"low": correct / n, "high": (correct + pending) / n} if n else None,
            "wilson_95": wilson_95(correct, n) if not pending else None,
            "headline_eligible": included,
            "small_sample": 0 < n < SMALL_TOPIC_N,
            "headline_weight": None,  # Filled once the headline denominator is known.
        })
    headline_n = sum(entry["n"] for entry in topic_reports)
    headline_correct = sum(entry["correct"] for entry in topic_reports)
    headline_pending = sum(entry["pending_adjudication"] for entry in topic_reports)
    for entry in topic_reports:
        entry["headline_weight"] = entry["n"] / headline_n if headline_n else 0.0
    accuracies = [entry["accuracy"] for entry in topic_reports if entry["accuracy"] is not None]

    separate = {}
    for track in sorted(other_tracks):
        values = other_tracks[track]
        if track == "proof_certificate":
            separate[track] = {
                "n": len(values),
                "definite_zero": sum(credit == 0 for credit, _ in values),
                "pending_external_verification": sum(credit is None for credit, _ in values),
                "accuracy": None,
                "time_limit_minutes": 60,
            }
        else:
            n = len(values)
            correct = sum(credit == 1 for credit, _ in values)
            pending = sum(credit is None for credit, _ in values)
            separate[track] = {
                "correct": correct, "n": n, "pending_adjudication": pending,
                "accuracy": correct / n if n and not pending else None,
                "accuracy_bounds": {"low": correct / n, "high": (correct + pending) / n} if n else None,
                "wilson_95": wilson_95(correct, n) if not pending else None,
                "affects_headline": False,
                "time_limit_minutes": 30,
            }
    return {
        "report_version": "2.0.0",
        "scoring_policy": {
            "core": "binary answer-only credit after exact/safe numeric matching or explicit adjudication; no partial credit",
            "normalization": "Unicode NFKC, outer math delimiters/boxed, whitespace/casefold, numeric fractions/arithmetic and compatible units",
            "answer_only_time_limit_minutes": 30,
            "proof_certificate_time_limit_minutes": 60,
            "missing_prediction_abstention_timeout_invalid": "zero credit",
            "all_answer_only_core_topics_in_headline": True,
            "small_topic_n_below": SMALL_TOPIC_N,
            "unresolved_equivalence": "pending adjudication; final accuracy and Wilson interval suppressed until resolved",
            "constructive_witness": "a different answer to a best-known example requires constraint verification; never auto-marked wrong",
            "proof_certificates": "not automatically graded; nonzero submissions require a proof verifier",
        },
        "prediction_coverage": {
            "dataset_items": len(dataset),
            "prediction_items": len(predictions),
            "missing_items": len(dataset) - len(predictions),
        },
        "headline": {
            "correct": headline_correct,
            "n": headline_n,
            "pending_adjudication": headline_pending,
            "accuracy": headline_correct / headline_n if headline_n and not headline_pending else None,
            "accuracy_bounds": {"low": headline_correct / headline_n,
                                "high": (headline_correct + headline_pending) / headline_n} if headline_n else None,
            "wilson_95": wilson_95(headline_correct, headline_n) if not headline_pending else None,
            "eligible_topic_count": sum(entry["headline_eligible"] for entry in topic_reports),
            "small_sample_topic_count": sum(entry["small_sample"] for entry in topic_reports),
            "method": "item-weighted micro-average over all answer-only core topics",
        },
        "per_topic": topic_reports,
        "macro_diagnostic": {
            "accuracy": sum(accuracies) / len(accuracies) if len(accuracies) == sum(entry["n"] > 0 for entry in topic_reports) and accuracies else None,
            "topic_count": sum(entry["n"] > 0 for entry in topic_reports),
            "affects_headline": False,
        },
        "adjudications_applied_by_reviewer_type": dict(sorted(applied_adjudications.items())),
        "pending_adjudication_ids": sorted(pending_item_ids),
        "separate_tracks": separate,
        "outcome_counts_all_tracks": dict(sorted(outcome_counts.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Final package directory, topics directory, or one topic JSONL")
    parser.add_argument("--predictions", type=Path, required=True, help="Prediction JSONL with id and final_answer or answer")
    parser.add_argument("--output", type=Path, required=True, help="JSON report destination")
    parser.add_argument("--review-queue", type=Path, help="Private JSONL review queue; contains gold answers")
    parser.add_argument("--adjudications", type=Path, help="Private JSONL with explicit semantic-review decisions")
    args = parser.parse_args(argv)
    try:
        if args.review_queue and args.review_queue.resolve() == args.output.resolve():
            raise ValueError("review queue and report must be different files")
        dataset = load_dataset(args.dataset)
        predictions = load_predictions(args.predictions, set(dataset))
        adjudications = load_adjudications(args.adjudications, set(dataset)) if args.adjudications else {}
        report = score(dataset, predictions, adjudications)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.review_queue:
            args.review_queue.parent.mkdir(parents=True, exist_ok=True)
            queue = []
            for item_id in report["pending_adjudication_ids"]:
                item = dataset[item_id]
                prediction = predictions[item_id]
                _, reason = item_result(item, prediction)
                queue.append({
                    "id": item_id, "topic": item["domain_primary"], "reason": reason,
                    "prediction": prediction.get("final_answer", prediction.get("answer")),
                    "answer_only": item["answer_only"],
                })
            args.review_queue.write_text(
                "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in queue),
                encoding="utf-8",
            )
            args.review_queue.chmod(0o600)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
