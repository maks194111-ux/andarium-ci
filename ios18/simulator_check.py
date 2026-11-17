#!/usr/bin/env python3
"""Select exact installed iOS runtimes and classify simulator boot evidence."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def select(runtimes, devices, major, requested_device):
    available = [
        r for r in runtimes["runtimes"]
        if r.get("isAvailable") and
        r.get("identifier", "").startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
        and r.get("version", "").split(".")[0] == major
    ]
    if not available:
        raise ValueError(f"No available iOS {major} runtime; no substitute was used")
    # Several runtimes can share a version (for example a second 27.2 build
    # that supports a single device type); try the newest first and, within a
    # version, the one that supports the most device types.
    available.sort(key=lambda r: (tuple(int(n) for n in r["version"].split(".")),
                                  len(r.get("supportedDeviceTypes", []))), reverse=True)
    for runtime in available:
        allowed = {d["identifier"] for d in runtime.get("supportedDeviceTypes", [])}
        candidates = [
            d for d in devices["devicetypes"]
            if not allowed or d["identifier"] in allowed
        ]
        if requested_device == "iPad-Pro-auto":
            candidates = [d for d in candidates if d["name"].startswith("iPad Pro")]
            candidates.sort(key=lambda d: d["name"], reverse=True)
        else:
            candidates = [
                d for d in candidates
                if d["identifier"] == f"com.apple.CoreSimulator.SimDeviceType.{requested_device}"
            ]
        if candidates:
            return runtime, candidates[0]
    raise ValueError(f"No installed compatible device type for {requested_device}")


def classify(console, alive):
    stopped = bool(re.search(r"Andarium: runtime returned|UML: cannot reserve", console))
    ready = "Andarium: boot reached ready" in console
    # A display that could not show a frame leaves a black screen while every
    # other sign of a healthy boot is present.
    display_failed = "Native Metal display failed" in console
    return {
        "status": "failed" if stopped or not alive or display_failed else "passed" if ready else "not_ready",
        "display_failed": display_failed,
        "android_ready": ready,
        "kernel_started": bool(re.search(r"boot reached (kernelRunning|androidStarting)", console)),
        "first_frame": "first frame copied" in console,
        "runtime_stopped_or_window_failed": stopped,
        "host_process_alive": alive,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["select", "result"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--major")
    parser.add_argument("--device")
    parser.add_argument("--alive", choices=["yes", "no"])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result_file = args.output / "result.json"
    if args.mode == "select":
        runtimes = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "runtimes", "-j"]))
        devices = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "devicetypes", "-j"]))
        (args.output / "runtimes.json").write_text(json.dumps(runtimes, indent=2))
        (args.output / "devices.json").write_text(json.dumps(devices, indent=2))
        result = {"requested_major": args.major, "requested_device": args.device}
        try:
            runtime, device = select(runtimes, devices, args.major, args.device)
        except ValueError as error:
            result.update(status="unavailable", reason=str(error))
            result_file.write_text(json.dumps(result, indent=2))
            print(str(error))
            raise SystemExit(2)
        result.update(status="pending", runtime=runtime["identifier"], version=runtime["version"],
                      device=device["identifier"], device_name=device["name"])
        result_file.write_text(json.dumps(result, indent=2))
        print(runtime["identifier"], device["identifier"])
    else:
        result = json.loads(result_file.read_text())
        console = (args.output / "console-start.txt").read_text(errors="replace")
        result.update(classify(console, args.alive == "yes"))
        result["crashes"] = []
        for report in args.output.glob("*.ips"):
            try:
                data = json.loads(report.read_text().split("\n", 1)[1])
            except (ValueError, IndexError):
                continue
            termination = data.get("termination", {})
            result["crashes"].append({
                "file": report.name,
                "exception": data.get("exception"),
                "termination": termination,
            })
            if report.name.startswith("Andarium") and termination.get("namespace") == "METAL" and any(
                "SimMetalHost" in reason for reason in termination.get("reasons", [])
            ):
                result["status"] = "simulator_failure"
                result["reason"] = "App lost its connection to the simulator Metal service"
        result["scope"] = "Simulator only; not physical-device CPU, memory limits, GPU or signing validation"
        result_file.write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
