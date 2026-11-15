#!/usr/bin/env python3
import unittest
from simulator_check import classify, select


class SimulatorChecks(unittest.TestCase):
    def setUp(self):
        self.devices = {"devicetypes": [{
            "identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-11",
            "name": "iPhone 11",
        }]}
        self.runtimes = {"runtimes": [{
            "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-6",
            "version": "18.6", "isAvailable": True,
        }]}

    def test_exact_major(self):
        runtime, device = select(self.runtimes, self.devices, "18", "iPhone-11")
        self.assertEqual(runtime["version"], "18.6")
        self.assertEqual(device["name"], "iPhone 11")

    def test_never_substitute_18_for_27(self):
        with self.assertRaises(ValueError):
            select(self.runtimes, self.devices, "27", "iPhone-11")

    def test_missing_device(self):
        with self.assertRaises(ValueError):
            select(self.runtimes, self.devices, "18", "iPhone-16-Pro")

    def test_unavailable_runtime(self):
        self.runtimes["runtimes"][0]["isAvailable"] = False
        with self.assertRaises(ValueError):
            select(self.runtimes, self.devices, "18", "iPhone-11")

    def test_alive_is_not_boot_success(self):
        self.assertEqual(classify("boot reached kernelRunning", True)["status"], "not_ready")

    def test_ready_and_alive(self):
        self.assertEqual(classify("Andarium: boot reached ready", True)["status"], "passed")

    def test_ready_then_runtime_failure(self):
        self.assertEqual(classify("Andarium: boot reached ready\nAndarium: runtime returned -4", True)["status"], "failed")

    def test_ready_then_process_exit(self):
        self.assertEqual(classify("Andarium: boot reached ready", False)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
