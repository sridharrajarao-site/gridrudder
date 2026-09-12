import unittest

from gridgpu.faults import (
    FaultInjection,
    FaultInjector,
    FaultKind,
    LeaseFence,
    manual_precedence,
    validate_optimizer_output,
)


class FaultFrameworkTests(unittest.TestCase):
    def test_plan_is_deterministic_single_use_and_must_be_consumed(self):
        injector = FaultInjector(
            (
                FaultInjection(2, FaultKind.AUDIT_FAILURE, "later"),
                FaultInjection(1, FaultKind.METER_LOSS, "first"),
            )
        )
        self.assertIsNone(injector.trigger(0, FaultKind.METER_LOSS))
        self.assertEqual(injector.trigger(1, FaultKind.METER_LOSS).detail, "first")
        self.assertIsNone(injector.trigger(1, FaultKind.METER_LOSS))
        with self.assertRaises(AssertionError):
            injector.require_fully_consumed()
        injector.trigger(2, FaultKind.AUDIT_FAILURE)
        injector.require_fully_consumed()
        self.assertEqual([item.kind for item in injector.observed], [FaultKind.METER_LOSS, FaultKind.AUDIT_FAILURE])

    def test_duplicate_fault_key_is_rejected(self):
        with self.assertRaises(ValueError):
            FaultInjector(
                (
                    FaultInjection(1, FaultKind.METER_LOSS, "one"),
                    FaultInjection(1, FaultKind.METER_LOSS, "two"),
                )
            )

    def test_lease_epoch_fences_stale_controller(self):
        fence = LeaseFence()
        old = fence.acquire("old")
        current = fence.acquire("current")
        self.assertFalse(fence.assess("old", old).authorized)
        self.assertTrue(fence.assess("current", current).authorized)

    def test_manual_precedence_is_stricter_and_optimizer_validation_fails_closed(self):
        self.assertEqual(manual_precedence(8_000, 10_000)[0], 8_000)
        self.assertFalse(validate_optimizer_output(None)[0])
        self.assertFalse(validate_optimizer_output({"actions": "bad"})[0])
        self.assertTrue(validate_optimizer_output({"actions": []})[0])


if __name__ == "__main__":
    unittest.main()

