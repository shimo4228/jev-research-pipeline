"""Idempotent stage cache (decision 8): (stage, input content hash) → output @ids.

A stage is done for an input iff its StageRecord exists AND every recorded output is
still in the partition. A dangling record (outputs removed) counts as not done, so the
stage reruns instead of the pipeline trusting nodes that are gone.
"""

import json

from pydantic import AwareDatetime, JsonValue

from jev_research_pipeline.model import StageRecord, sha256_hex

from .graph import Partition


def input_sha256(payload: JsonValue) -> str:
    """Hash of a stage input in canonical JSON: sorted keys, compact separators, UTF-8,
    no ASCII escaping. The form is pinned by a golden test — changing it invalidates
    every cached stage."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_hex(canonical)


class StageCache:
    """Stage records live in the same partition as the outputs they point to."""

    def __init__(self, partition: Partition) -> None:
        self.partition = partition

    def lookup(self, stage: str, input_hash: str) -> tuple[str, ...] | None:
        nodes = self.partition.load()
        record = nodes.get(StageRecord.id_for(stage, input_hash))
        if not isinstance(record, StageRecord):
            return None
        if any(out not in nodes for out in record.outputs):
            return None
        return record.outputs

    def record(
        self, stage: str, input_hash: str, outputs: tuple[str, ...], now: AwareDatetime
    ) -> StageRecord:
        rec = StageRecord.new(
            stage=stage, input_sha256=input_hash, outputs=outputs, completed_at=now
        )
        self.partition.put([rec])
        return rec
