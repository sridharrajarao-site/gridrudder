"""Parent/child CLI handshake tests; every hardware boundary is mocked."""
from contextlib import redirect_stdout
from dataclasses import asdict
import io
import hashlib
import json
import sys
import unittest
from unittest.mock import patch, Mock

import test_rental_execution as fixtures
from gridgpu.rental_execution import main


class RentalCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RentalExecutionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.settings = f.base / "settings.json"
        self.settings.write_text(json.dumps(dict(config=asdict(f.config),
            authorization=asdict(f.authorization), intent=asdict(f.intent), signed=asdict(f.signed),
            authority_directory=str(f.keys), run_directory=str(f.run), recipe_path=str(f.path))))
        self.argv = ["rental", "--settings", str(self.settings), "--execute-approved-trial"]

    def test_parent_passes_confirmed_phrase_to_controller(self):
        phrase = "RUN host GPU-fixture 125.000W"
        with patch.object(sys, "argv", self.argv), patch("builtins.input", return_value=phrase), \
                patch("gridgpu.rental_execution.LocalApprovalAuthority", return_value=self.fixture.authority), \
                patch("gridgpu.rental_execution.NvidiaSingleGpuPowerControl", QUERY="fixture-query",
                      return_value=Mock(observe_limit=Mock(return_value=175), evidence=[])), \
                patch("gridgpu.rental_execution.supervise_attended_controller", return_value={"fixture": True}) as supervise, \
                redirect_stdout(io.StringIO()):
            main()
        args, kwargs = supervise.call_args
        self.assertIn("--controller", args[0])
        self.assertIn(str(self.settings.resolve()), args[0])
        self.assertIn("--supervisor-pid", args[0])
        self.assertEqual(args[0][args[0].index("--settings-sha256") + 1],
                         hashlib.sha256(self.settings.read_bytes()).hexdigest())
        self.assertEqual(kwargs["controller_input"], phrase + "\n")
        self.assertGreater(kwargs["maximum_seconds"], 0)

    def test_rejected_confirmation_never_launches_controller(self):
        with patch.object(sys, "argv", self.argv), patch("builtins.input", return_value="no"), \
                patch("gridgpu.rental_execution.LocalApprovalAuthority", return_value=self.fixture.authority), \
                patch("gridgpu.rental_execution.supervise_attended_controller") as supervise:
            with self.assertRaisesRegex(ValueError, "confirmation"):
                main()
        supervise.assert_not_called()

    def test_child_dispatch_retains_exact_signed_settings(self):
        with patch.object(sys, "argv", self.argv + ["--controller", "--supervisor-pid", "123",
                "--settings-sha256", hashlib.sha256(self.settings.read_bytes()).hexdigest()]), \
                patch("gridgpu.rental_execution.arm_parent_death") as armed, \
                patch("gridgpu.rental_execution.run_rental_trial") as run:
            main()
        armed.assert_called_once_with(123)
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["config"], self.fixture.config)
        self.assertEqual(kwargs["authorization"], self.fixture.authorization)
        self.assertEqual(kwargs["intent"], self.fixture.intent)
        self.assertEqual(kwargs["signed"], self.fixture.signed)

    def test_settings_mutation_rejected_before_arm_or_controller(self):
        expected = hashlib.sha256(self.settings.read_bytes()).hexdigest()
        self.settings.write_text(self.settings.read_text() + "\n")
        with patch.object(sys, "argv", self.argv + ["--controller", "--supervisor-pid", "123",
                "--settings-sha256", expected]), patch("gridgpu.rental_execution.arm_parent_death") as armed, \
                patch("gridgpu.rental_execution.run_rental_trial") as run:
            with self.assertRaises(ValueError):
                main()
        armed.assert_not_called()
        run.assert_not_called()

    def test_explicit_execution_flag_required(self):
        with patch.object(sys, "argv", self.argv[:-1]), \
                patch("gridgpu.rental_execution.run_rental_trial") as run, \
                redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                main()
        run.assert_not_called()
