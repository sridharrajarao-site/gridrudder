import unittest

from gridgpu.domain import Action, Flexibility, Priority, Workload
from gridgpu.policy import (
    AuthorizationContext,
    FlexibilityPolicyGuard,
    PolicyViolation,
    WorkloadPolicy,
)


def flexible_workload(state="running", current_cap=None):
    return Workload(
        "flex",
        Priority.OPPORTUNISTIC,
        4,
        0,
        10_000,
        350,
        Flexibility(may_defer=True, may_power_cap=True, min_power_watts_per_gpu=180),
        state=state,
        current_cap_watts=current_cap,
    )


def policy(maximum_actions=3):
    return WorkloadPolicy(
        "flex",
        "tenant-a",
        ("operator-a",),
        may_defer=True,
        may_power_cap=True,
        minimum_power_watts_per_gpu=200,
        maximum_event_duration_seconds=600,
        maximum_actions_per_event=maximum_actions,
    )


def context(**changes):
    values = dict(
        tenant_id="tenant-a",
        operator_id="operator-a",
        event_id="event-1",
        event_duration_seconds=300,
    )
    values.update(changes)
    return AuthorizationContext(**values)


class FlexibilityPolicyGuardTests(unittest.TestCase):
    def test_unknown_workload_defaults_protected(self):
        guard = FlexibilityPolicyGuard()
        decision = guard.assess(
            Action("set_power_cap", "flex", 250, "constraint"), flexible_workload(), context()
        )
        self.assertFalse(decision.authorized)
        self.assertIn("unknown workload is protected", decision.reasons)

    def test_tenant_and_operator_scopes_are_both_required(self):
        guard = FlexibilityPolicyGuard((policy(),))
        action = Action("set_power_cap", "flex", 250, "constraint")
        wrong_tenant = guard.assess(action, flexible_workload(), context(tenant_id="tenant-b"))
        wrong_operator = guard.assess(action, flexible_workload(), context(operator_id="operator-b"))
        self.assertIn("tenant is not authorized for workload", wrong_tenant.reasons)
        self.assertIn("operator is not authorized for workload", wrong_operator.reasons)

    def test_valid_queued_deferral_is_authorized(self):
        guard = FlexibilityPolicyGuard((policy(),))
        action = Action("defer", "flex", None, "constraint")
        self.assertTrue(guard.assess(action, flexible_workload(state="queued"), context()).authorized)

    def test_deferral_is_rejected_for_running_work_or_recovery(self):
        guard = FlexibilityPolicyGuard((policy(),))
        action = Action("defer", "flex", None, "constraint")
        self.assertFalse(guard.assess(action, flexible_workload(), context()).authorized)
        recovering = guard.assess(
            action, flexible_workload(state="queued"), context(recovery=True)
        )
        self.assertIn("deferral is forbidden during recovery", recovering.reasons)

    def test_stricter_of_policy_and_workload_cap_floors_applies(self):
        guard = FlexibilityPolicyGuard((policy(),))
        rejected = guard.assess(
            Action("set_power_cap", "flex", 199, "constraint"), flexible_workload(), context()
        )
        accepted = guard.assess(
            Action("set_power_cap", "flex", 200, "constraint"), flexible_workload(), context()
        )
        self.assertIn("power cap is below authorized floor", rejected.reasons)
        self.assertTrue(accepted.authorized)

    def test_policy_cannot_broaden_workload_declaration(self):
        workload = flexible_workload()
        workload.flexibility = Flexibility(may_defer=True, may_power_cap=False)
        decision = FlexibilityPolicyGuard((policy(),)).assess(
            Action("set_power_cap", "flex", 250, "constraint"), workload, context()
        )
        self.assertIn("power capping is not authorized", decision.reasons)

    def test_duration_and_action_budget_fail_closed(self):
        guard = FlexibilityPolicyGuard((policy(maximum_actions=2),))
        action = Action("set_power_cap", "flex", 250, "constraint")
        too_long = guard.assess(action, flexible_workload(), context(event_duration_seconds=601))
        exhausted = guard.assess(action, flexible_workload(), context(actions_already_used=2))
        self.assertIn("event exceeds authorized duration", too_long.reasons)
        self.assertIn("event action budget exhausted", exhausted.reasons)

    def test_batch_budget_is_atomic_and_counts_each_action(self):
        guard = FlexibilityPolicyGuard((policy(maximum_actions=2),))
        workload = flexible_workload()
        actions = (
            Action("set_power_cap", "flex", 300, "constraint"),
            Action("set_power_cap", "flex", 250, "constraint"),
        )
        guard.validate_actions(actions, {"flex": workload}, context())
        with self.assertRaises(PolicyViolation):
            guard.validate_actions(actions, {"flex": workload}, context(actions_already_used=1))

    def test_constraint_cannot_remove_or_raise_cap(self):
        guard = FlexibilityPolicyGuard((policy(),))
        workload = flexible_workload(current_cap=250)
        self.assertFalse(
            guard.assess(Action("set_power_cap", "flex", None, "bad"), workload, context()).authorized
        )
        self.assertFalse(
            guard.assess(Action("set_power_cap", "flex", 260, "bad"), workload, context()).authorized
        )

    def test_recovery_is_monotonic_and_bounded_by_nominal_power(self):
        guard = FlexibilityPolicyGuard((policy(),))
        workload = flexible_workload(current_cap=250)
        recovery = context(recovery=True)
        self.assertTrue(
            guard.assess(Action("set_power_cap", "flex", 275, "recover"), workload, recovery).authorized
        )
        self.assertTrue(
            guard.assess(Action("set_power_cap", "flex", None, "recover"), workload, recovery).authorized
        )
        lower = guard.assess(Action("set_power_cap", "flex", 225, "bad"), workload, recovery)
        above_nominal = guard.assess(
            Action("set_power_cap", "flex", 351, "bad"), workload, recovery
        )
        self.assertIn("recovery may not lower a power cap", lower.reasons)
        self.assertIn("recovery cap exceeds nominal workload power", above_nominal.reasons)

    def test_uncapped_workload_has_nothing_to_recover(self):
        result = FlexibilityPolicyGuard((policy(),)).assess(
            Action("set_power_cap", "flex", None, "recover"),
            flexible_workload(),
            context(recovery=True),
        )
        self.assertIn("uncapped workload has nothing to recover", result.reasons)


if __name__ == "__main__":
    unittest.main()
