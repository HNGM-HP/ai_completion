from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class ConfidenceThresholds:
    low: float
    high: float


@dataclass(frozen=True)
class BranchSpecs:
    raw: dict[str, Any]
    confidence_thresholds: ConfidenceThresholds


def load_branch_specs(file_path: str) -> BranchSpecs:
    """加载分支配置。

    只做最小结构化：把 gating.confidence_thresholds 抽出来。
    其余保持 raw 字典，便于后续快速加字段而不改代码。
    """

    with open(file_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    gating = raw.get("gating") or {}
    thresholds = gating.get("confidence_thresholds") or {}

    low = float(thresholds.get("low", 0.55))
    high = float(thresholds.get("high", 0.80))
    if not (0.0 <= low <= 1.0 and 0.0 <= high <= 1.0 and low <= high):
        raise ValueError("branch_specs.yaml gating.confidence_thresholds 取值不合法")

    return BranchSpecs(
        raw=raw,
        confidence_thresholds=ConfidenceThresholds(low=low, high=high),
    )
