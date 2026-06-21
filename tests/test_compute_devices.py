"""Tests for device probe registry and GPU/CPU/NPU capability fingerprinting.

Covers device enumeration, backend probing, capability detection, and udev hotplug.
Tests ensure all present backends are discovered, unavailable devices are recorded
with structured reasons, and probes do not unexpectedly import heavy dependencies
on CPU-only environments.

Reference: docs/design/phase11/sections/20-tests.md §11.20
"""

import pytest


class TestDeviceProbe:
    """Test suite for device probe and backend enumeration."""

    def test_device_probe_enumerates_all_backends(self):
        """Every present backend appears in device.json; absent ones are unavailable with reason.
        
        TODO: implement when Phase 11 lands and device.py probe is complete
        """
        pass

    def test_device_probe_subprocess_timeout(self):
        """Wedged probe times out in 5s; affected device recorded as unavailable.
        
        TODO: implement when Phase 11 lands
        """
        pass

    def test_device_probe_no_top_level_torch_import(self):
        """Importing probe module on CPU-only image does not pull torch at top level.
        
        TODO: implement when Phase 11 lands
        """
        pass


class TestDeviceCapability:
    """Test suite for device fingerprinting and capability detection."""

    def test_device_capability_fingerprint_stable(self):
        """Same device always produces the same fingerprint on repeated probes.
        
        TODO: implement when Phase 11 lands
        """
        pass

    def test_cpu_baseline_fingerprint_simd_detection(self):
        """CPU SIMD flags (AVX2, AVX-512, etc.) are detected correctly in fingerprint.
        
        TODO: implement when Phase 11 lands
        """
        pass

    def test_device_hotplug_udev_trigger(self):
        """udev event re-runs probe; topology delta is emitted as a bus event.
        
        TODO: implement when Phase 11 lands
        """
        pass


class TestDeviceUnavailability:
    """Test suite for device unavailability tracking and reasons."""

    def test_device_probe_timeout_marks_unavailable(self):
        """Probe timeout marks device as unavailable with reason=probe_timeout.
        
        TODO: implement when Phase 11 lands
        """
        pass
