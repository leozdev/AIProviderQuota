"""Exercise removal with fake CLIs; never touch the running Plasma session."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UninstallContracts(unittest.TestCase):
    def run_removal(self, bus_status, package_status=0):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bus = directory / 'qdbus6'
            bus.write_text('#!/bin/sh\nexit %d\n' % bus_status)
            package = directory / 'kpackagetool6'
            package.write_text('#!/bin/sh\nprintf "%%s\\n" "$@" > "$REMOVE_ARGS"\nexit %d\n' % package_status)
            bus.chmod(0o700)
            package.chmod(0o700)
            record = directory / 'args'
            env = dict(os.environ, PATH=str(directory), REMOVE_ARGS=str(record))
            result = subprocess.run(['/usr/bin/bash', str(ROOT / 'uninstall.sh')],
                                    env=env, capture_output=True, text=True, timeout=3)
            return result, record.read_text().splitlines()

    def test_package_removal_survives_missing_plasma_session(self):
        result, args = self.run_removal(1)
        self.assertEqual(result.returncode, 0)
        self.assertIn('Warning:', result.stderr)
        self.assertEqual(args, ['--type', 'Plasma/Applet', '--remove', 'org.leoz.aiquotas'])

    def test_normal_removal_has_no_warning(self):
        result, _ = self.run_removal(0)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, '')

    def test_package_failure_is_propagated(self):
        result, _ = self.run_removal(1, 7)
        self.assertEqual(result.returncode, 7)
        self.assertNotIn('Widget removed.', result.stdout)
