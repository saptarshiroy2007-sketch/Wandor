"""
Auto MCQ generation. This is a stub — plug in an LLM call here (Claude API is the obvious
choice: send it the topic + grade level, ask for strict JSON output of N questions).
Keeping this as its own module means you can swap the generation strategy later
(LLM vs a static question bank vs scraping NCERT question sets) without touching routers.
"""
import json
from typing import List, Dict


def generate_mcqs(topic: str, num_questions: int, grade_level: str = "class 10") -> List[Dict]:
    """
    Returns a list of dicts like:
    {"text": ..., "option_a": ..., "option_b": ..., "option_c": ..., "option_d": ..., "correct_option": "a"}

    TODO: replace this stub with a real call, e.g.:

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"Generate {num_questions} MCQs for {grade_level} on '{topic}'. "
                        f"Return ONLY a JSON array, no prose, each item with keys: "
                        f"text, option_a, option_b, option_c, option_d, correct_option (a/b/c/d)."
        }]
    )
    return json.loads(response.content[0].text)
    """
    return [
        {
            "text": f"[PLACEHOLDER] Sample question {i+1} on {topic}",
            "option_a": "Option A",
            "option_b": "Option B",
            "option_c": "Option C",
            "option_d": "Option D",
            "correct_option": "a",
        }
        for i in range(num_questions)
    ]
