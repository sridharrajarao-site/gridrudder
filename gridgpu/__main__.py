import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .audit import verify_audit_log
from .benchmarks import run_canonical_benchmarks
from .controller import HeuristicController
from .domain import Flexibility, PowerEnvelope, Priority, Workload
from .nvml import NvidiaSmiShadowAdapter
from .simulator import Simulator
from .reporting import summarize
from .release import run_gate_b_release


def demo(output: Path) -> None:
    workloads = [
        Workload("critical-inference", Priority.CRITICAL, 2, 0, 10_000, 300),
        Workload("flexible-training", Priority.OPPORTUNISTIC, 8, 0, 10_000, 350, Flexibility(True, True, 180)),
        Workload("later-batch", Priority.OPPORTUNISTIC, 4, 20, 2_000, 300, Flexibility(True, True, 160)),
    ]
    envelopes = [PowerEnvelope(0, 6_000), PowerEnvelope(30, 3_800), PowerEnvelope(90, 6_000)]
    simulator = Simulator(workloads, envelopes, HeuristicController())
    simulator.run(150)
    simulator.write_jsonl(output)
    summary = summarize(simulator.audit)
    print("wrote {} records to {}".format(len(simulator.audit), output))
    print("compliance: {:.2%}".format(summary.compliance_ratio))
    print("maximum envelope exceedance: {:.1f} W".format(summary.maximum_exceedance_watts))
    print("energy over limit: {:.3f} Wh".format(summary.energy_over_limit_wh))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument("--output", type=Path, default=Path("artifacts/demo.jsonl"))
    subparsers.add_parser("benchmark")
    subparsers.add_parser("probe-nvidia")
    verify_parser = subparsers.add_parser("verify-audit")
    verify_parser.add_argument("path", type=Path)
    release_parser = subparsers.add_parser("gate-b-release")
    release_parser.add_argument("--output", type=Path)
    trial_parser = subparsers.add_parser("hardware-trial")
    trial_parser.add_argument("--gpu-uuid", required=True)
    trial_parser.add_argument("--target-watts", required=True, type=float)
    trial_parser.add_argument("--approval-id", required=True)
    trial_parser.add_argument("--actor", default="operator:gridrudder-lab")
    trial_parser.add_argument("--settle-seconds", type=float, default=5.0)
    trial_parser.add_argument("--audit", type=Path, required=True)
    trial_parser.add_argument("--nvidia-smi", default="nvidia-smi")
    trial_parser.add_argument("--ipmitool", default="ipmitool")
    trial_parser.add_argument("--ipmitool-library-path")
    trial_parser.add_argument("--enable-physical-actuation", action="store_true")
    args = parser.parse_args()
    if args.command == "demo":
        demo(args.output)
    elif args.command == "benchmark":
        results = run_canonical_benchmarks()
        for result in results:
            print(json.dumps(asdict(result), sort_keys=True))
        if not all(result.passed for result in results):
            raise SystemExit(1)
    elif args.command == "probe-nvidia":
        adapter = NvidiaSmiShadowAdapter()
        capabilities = adapter.capabilities()
        print(json.dumps(asdict(capabilities), sort_keys=True))
        if capabilities.telemetry_available:
            for device in adapter.list_devices():
                print(json.dumps(asdict(device), sort_keys=True))
    elif args.command == "verify-audit":
        print(json.dumps(asdict(verify_audit_log(args.path)), sort_keys=True))
    elif args.command == "gate-b-release":
        release = run_gate_b_release(args.output)
        print(json.dumps(asdict(release.gate_decision), sort_keys=True))
        print(str(release.decision_path))
        if not release.gate_decision.go:
            raise SystemExit(1)
    elif args.command == "hardware-trial":
        raise SystemExit(
            "legacy hardware-trial is disabled; physical trials must use the "
            "attended performance path with bound authorization, preflight, "
            "locking, workload identity, and restoration evidence"
        )


if __name__ == "__main__":
    main()
