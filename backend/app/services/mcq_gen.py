"""
Auto MCQ generation. Deterministic-first per the GymCoach precedent: this is the ONE
genuinely non-deterministic/LLM-backed piece of Wandor (like GymCoach kept exactly one
Gemini call for Trainer Review) - everything else (attendance %, rank, fee logic) should
stay rule-based, not routed through here or any other LLM call.

Falls back to a clearly-labeled placeholder stub if ANTHROPIC_API_KEY isn't set, so the
app never hard-fails in dev/demo environments without a key configured.
"""
import json
import re
from typing import List, Dict

from ..database import settings

VALID_OPTIONS = {"a", "b", "c", "d"}


def _placeholder_mcqs(topic: str, num_questions: int) -> List[Dict]:
    return [
        {
            "text": f"[PLACEHOLDER - set ANTHROPIC_API_KEY for real questions] Sample question {i+1} on {topic}",
            "option_a": "Option A",
            "option_b": "Option B",
            "option_c": "Option C",
            "option_d": "Option D",
            "correct_option": "a",
        }
        for i in range(num_questions)
    ]


def _validate(questions: List[Dict]) -> List[Dict]:
    """Drop any question the model returned in a shape that would break the DB insert
    or leak an invalid correct_option - never trust LLM output shape blindly."""
    required_keys = {"text", "option_a", "option_b", "option_c", "option_d", "correct_option"}
    valid = []
    for q in questions:
        if not isinstance(q, dict) or not required_keys.issubset(q.keys()):
            continue
        if str(q["correct_option"]).lower() not in VALID_OPTIONS:
            continue
        q["correct_option"] = str(q["correct_option"]).lower()
        valid.append(q)
    return valid


def generate_mcqs(topic: str, num_questions: int, grade_level: str = "class 10") -> List[Dict]:
    """
    Returns a list of dicts like:
    {"text": ..., "option_a": ..., "option_b": ..., "option_c": ..., "option_d": ..., "correct_option": "a"}
    """
    if not settings.anthropic_api_key:
        return _placeholder_mcqs(topic, num_questions)

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    prompt = (
        f"Generate exactly {num_questions} multiple-choice questions for {grade_level} students "
        f"on the topic '{topic}'. Return ONLY a raw JSON array, no prose, no markdown fences. "
        f"Each item must be an object with exactly these keys: "
        f'"text", "option_a", "option_b", "option_c", "option_d", "correct_option" '
        f'(one of "a", "b", "c", "d"). Vary the position of the correct answer across questions.'
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = "".join(block.text for block in response.content if block.type == "text")
        # Strip markdown fences if the model adds them despite instructions
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(cleaned)
        validated = _validate(parsed)
        if not validated:
            return _placeholder_mcqs(topic, num_questions)
        return validated
    except Exception:
        # Network error, bad JSON, rate limit, etc - never let a test creation 500 out;
        # fall back to placeholders so the teacher isn't blocked, and can regenerate later.
        return _placeholder_mcqs(topic, num_questions)
