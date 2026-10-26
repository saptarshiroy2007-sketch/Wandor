"""Batch name normalization - trims and collapses whitespace on a batch NAME string
before it's stored as a Batch row (or matched against one). This is deliberately
small now: since migration 0011 made batch a real entity (app/models.py's Batch,
referenced everywhere via batch_id), the old batch_matches() case-insensitive SQL
comparator that used to paper over typos on every query is gone - a batch_id is
either the right id or it isn't, no fuzzy matching needed at query time anymore.
normalize_batch() still earns its keep at the two remaining points where a human
types a raw batch NAME rather than picking an existing batch_id: creating/renaming a
Batch (POST/PATCH /batches) and the CSV bulk-student-import column, both in
schemas.py.
"""
import re


def normalize_batch(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = re.sub(r"\s+", " ", value).strip()
    return collapsed or None
