from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class EventSummary:
    sample_count: int
    compliant_samples: int
    compliance_ratio: float
    maximum_exceedance_watts: float
    energy_over_limit_wh: float
    action_count: int


def summarize(records: Iterable[Mapping], sample_seconds: float = 1.0) -> EventSummary:
    samples = [row for row in records if row.get("type") == "sample"]
    actions = [row for row in records if row.get("type") == "action"]
    exceedances = [
        max(0.0, float(row["facility_power_watts"]) - float(row["envelope_watts"]))
        for row in samples
    ]
    compliant = sum(value == 0.0 for value in exceedances)
    count = len(samples)
    return EventSummary(
        sample_count=count,
        compliant_samples=compliant,
        compliance_ratio=(compliant / count) if count else 1.0,
        maximum_exceedance_watts=max(exceedances, default=0.0),
        energy_over_limit_wh=sum(exceedances) * sample_seconds / 3600.0,
        action_count=len(actions),
    )
