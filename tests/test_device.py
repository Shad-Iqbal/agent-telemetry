"""Device labels: fixture-only OS metadata, including older Python on Windows 11."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard as D


class DeviceLabelTests(unittest.TestCase):
    def label(self, version, product_type=1, release="10"):
        with patch.object(D.platform, "release", return_value=release), \
             patch.object(D.platform, "win32_ver", return_value=(release, version, "", "")), \
             patch.object(D.sys, "getwindowsversion", create=True,
                          return_value=SimpleNamespace(product_type=product_type)):
            return D._windows_os_label()

    def test_windows_11_client_builds_with_old_python_release(self):
        for build in (22000, 22621, 22631, 26100, 26200, 26300, 28000):
            with self.subTest(build=build):
                self.assertEqual(self.label(f"10.0.{build}"), "Windows 11")

    def test_windows_10_and_threshold_boundary(self):
        for build in (10240, 19045, 21999):
            with self.subTest(build=build):
                self.assertEqual(self.label(f"10.0.{build}"), "Windows 10")

    def test_server_and_unknown_product_types_are_not_windows_11(self):
        for product_type in (2, 3, 0):
            with self.subTest(product_type=product_type):
                self.assertEqual(self.label("10.0.26100", product_type), "Windows 10")
        self.assertEqual(self.label("10.0.26100", 3, "2025Server"), "Windows 2025Server")

    def test_existing_and_future_release_labels_are_preserved(self):
        for release in ("11", "8.1", "post11", ""):
            with self.subTest(release=release), \
                 patch.object(D.platform, "release", return_value=release), \
                 patch.object(D.platform, "win32_ver") as query:
                self.assertEqual(D._windows_os_label(), f"Windows {release}".strip())
                query.assert_not_called()
        self.assertEqual(self.label("10.1.28000"), "Windows 10")

    def test_unavailable_or_malformed_metadata_keeps_previous_label(self):
        for version in ("", "10.0", "invalid", None):
            with self.subTest(version=version):
                self.assertEqual(self.label(version), "Windows 10")
        for error in (AttributeError("unavailable"), OSError("unavailable")):
            with self.subTest(error=type(error).__name__), \
                 patch.object(D.platform, "release", return_value="10"), \
                 patch.object(D.sys, "getwindowsversion", create=True, side_effect=error):
                self.assertEqual(D._windows_os_label(), "Windows 10")

    def test_windows_device_uses_corrected_label_without_changing_identity(self):
        with patch.object(D.sys, "platform", "win32"), \
             patch.object(D.os, "name", "nt"), \
             patch.dict(D.os.environ, {"COMPUTERNAME": "Fixture PC"}), \
             patch.object(D.platform, "node", return_value="fixture-host"), \
             patch.object(D.platform, "release", return_value="10"), \
             patch.object(D.platform, "win32_ver", return_value=("10", "10.0.22631", "", "")), \
             patch.object(D.sys, "getwindowsversion", create=True,
                          return_value=SimpleNamespace(product_type=1)):
            self.assertEqual(D._device(), {"name": "Fixture PC", "host": "fixture-host",
                                          "os": "Windows 11"})


if __name__ == "__main__":
    unittest.main()
