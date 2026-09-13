"""Real trial, adapter, and journal composition; injected fake hardware only."""
import unittest
if __package__:
    from . import test_attended_benchmark_integration as fixtures
else:
    import test_attended_benchmark_integration as fixtures

from gridgpu.performance_trial import PerformanceTrialError
from gridgpu.recovery_journal import RecoveryIntent, RecoveryJournal
from gridgpu.supervised_recovery import JournaledPowerControl


class JournaledTrialIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AttendedBenchmarkIntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.journal = RecoveryJournal(f.directory / "recovery.jsonl")
        self.intent = RecoveryIntent("fixture-trial", f.config.host_id, f.config.gpu_uuid,
            f.authorization.binding_sha256, 175, 125, f.now.isoformat())
        f.control = JournaledPowerControl(f.control, self.journal, self.intent,
            verify_intent=lambda value: value == self.intent,
            clock=lambda: f.now, observation_source="fixture-readback")

    def test_success_closes_journal_and_final_restore_is_read_only(self):
        result = self.fixture.run_trial()
        self.assertTrue(result.restored)
        self.assertEqual(self.fixture.writes, [125, 175])
        self.assertEqual(self.journal.read().restored_observation.power_limit_watts, 175)

    def test_partial_cap_timeout_is_restored_and_closed(self):
        self.fixture.fault = "partial_cap_timeout"
        with self.assertRaisesRegex(PerformanceTrialError, "failed safely"):
            self.fixture.run_trial()
        self.assertEqual(self.fixture.writes, [125, 175])
        self.assertIsNotNone(self.journal.read().restored_observation)

    def test_failed_restore_preserves_unfinished_journal(self):
        self.fixture.fault = "restore_mismatch"
        with self.assertRaisesRegex(PerformanceTrialError, "CRITICAL"):
            self.fixture.run_trial()
        self.assertIsNone(self.journal.read().restored_observation)
        self.assertEqual(self.fixture.limit, 125)
