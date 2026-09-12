from datetime import datetime, timedelta, timezone
from dataclasses import replace
import unittest

from gridgpu.session import (
    ApprovalRequired,
    AuthorizationError,
    ControlSession,
    EnvelopeProposal,
    ExpiredProposal,
    HistoryReplayError,
    IdempotencyConflict,
    SessionState,
)
from gridgpu.telemetry import MeterSnapshot, Quality, TelemetrySample


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def proposal(proposal_id="env-1", watts=10_000.0):
    return EnvelopeProposal(
        proposal_id,
        watts,
        NOW,
        NOW + timedelta(minutes=5),
        "facility envelope test",
        "policy:v1",
    )


def meter(timestamp=NOW, quality=Quality.GOOD):
    sample = TelemetrySample(timestamp, 7, "pcc-1", 9_500.0, "W", quality, 20)
    return MeterSnapshot(sample, "pcc-1", maximum_watts=100_000)


def session():
    return ControlSession(frozenset({"operator:alice"}))


class ControlSessionTests(unittest.TestCase):
    def test_authorized_happy_path_emits_intent_but_does_not_write_hardware(self):
        control = session()
        proposed = control.propose(proposal(), actor="planner", now=NOW)
        self.assertEqual(control.state, SessionState.SUPERVISED)
        self.assertEqual(proposed.payload["previous_state"], "observe")
        control.approve(
            "env-1", approval_id="approval-1", approver="operator:alice", now=NOW
        )
        event = control.authorize_execution(
            "env-1", execution_id="execute-1", actor="controller", meter=meter(), now=NOW
        )
        self.assertEqual(event.event_type, "execution_authorized")
        self.assertTrue(event.payload["intent_only"])
        self.assertEqual(event.payload["approved_by"], "operator:alice")
        self.assertEqual(event.payload["meter_sequence"], 7)
        self.assertEqual(event.audit_arguments()[2], "controller")

    def test_execution_requires_explicit_authorized_approval(self):
        control = session()
        control.propose(proposal(), actor="planner", now=NOW)
        with self.assertRaises(ApprovalRequired):
            control.authorize_execution(
                "env-1", execution_id="execute-1", actor="controller", meter=meter(), now=NOW
            )
        with self.assertRaises(AuthorizationError):
            control.approve("env-1", approval_id="approval-x", approver="intruder", now=NOW)

    def test_stale_authoritative_telemetry_fails_closed(self):
        control = session()
        control.propose(proposal(), actor="planner", now=NOW)
        control.approve("env-1", approval_id="approval-1", approver="operator:alice", now=NOW)
        event = control.authorize_execution(
            "env-1",
            execution_id="execute-1",
            actor="controller",
            meter=meter(timestamp=NOW - timedelta(seconds=6)),
            now=NOW,
        )
        self.assertEqual(control.state, SessionState.SAFE_HOLD)
        self.assertEqual(event.event_type, "safe_hold_entered")
        self.assertIn("meter sample is stale", event.payload["eligibility_reasons"])
        self.assertNotIn("execute-1", [e.payload.get("execution_id") for e in control.events])

    def test_expiry_prevents_execution_and_enters_safe_hold(self):
        control = session()
        control.propose(proposal(), actor="planner", now=NOW)
        control.approve("env-1", approval_id="approval-1", approver="operator:alice", now=NOW)
        late = NOW + timedelta(minutes=5)
        with self.assertRaises(ExpiredProposal):
            control.authorize_execution(
                "env-1", execution_id="execute-1", actor="controller", meter=meter(late), now=late
            )
        self.assertEqual(control.state, SessionState.SAFE_HOLD)

    def test_execution_id_is_idempotent_and_conflicts_across_proposals(self):
        control = session()
        control.propose(proposal(), actor="planner", now=NOW)
        control.approve("env-1", approval_id="approval-1", approver="operator:alice", now=NOW)
        first = control.authorize_execution(
            "env-1", execution_id="execute-1", actor="controller", meter=meter(), now=NOW
        )
        second = control.authorize_execution(
            "env-1",
            execution_id="execute-1",
            actor="different-retrier",
            meter=meter(quality=Quality.BAD),
            now=NOW + timedelta(seconds=30),
        )
        self.assertIs(first, second)
        with self.assertRaises(IdempotencyConflict):
            control.authorize_execution(
                "different", execution_id="execute-1", actor="controller", meter=meter(), now=NOW
            )

    def test_duplicate_proposal_is_idempotent_but_changed_content_conflicts(self):
        control = session()
        control.propose(proposal(), actor="planner", now=NOW)
        duplicate = control.propose(proposal(), actor="planner", now=NOW)
        self.assertEqual(duplicate.event_type, "envelope_proposal_duplicate")
        with self.assertRaises(IdempotencyConflict):
            control.propose(proposal(watts=9_000), actor="planner", now=NOW)

    def test_approval_retry_keeps_original_identity_and_time(self):
        control = session()
        control.propose(proposal(), actor="planner", now=NOW)
        control.approve("env-1", approval_id="approval-1", approver="operator:alice", now=NOW)
        duplicate = control.approve(
            "env-1",
            approval_id="approval-1",
            approver="operator:alice",
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(duplicate.event_type, "approval_duplicate")
        self.assertEqual(control.approval.approved_at, NOW)

    def test_safe_hold_requires_authorized_fresh_recovery_then_observe(self):
        control = session()
        control.propose(proposal(), actor="planner", now=NOW)
        control.enter_safe_hold(reason="operator stop", actor="operator:alice", now=NOW)
        with self.assertRaises(AuthorizationError):
            control.begin_recovery(actor="intruder", meter=meter(), now=NOW)
        started = control.begin_recovery(actor="operator:alice", meter=meter(), now=NOW)
        self.assertEqual(started.event_type, "recovery_started")
        self.assertEqual(control.state, SessionState.RECOVERY)
        completed = control.complete_recovery(actor="operator:alice", now=NOW)
        self.assertEqual(completed.payload["state"], "observe")
        self.assertEqual(control.state, SessionState.OBSERVE)
        self.assertIsNone(control.proposal)

    def test_reconstructs_evidence_but_never_execution_and_requires_resume(self):
        original = session()
        original.propose(proposal(), actor="planner", now=NOW)
        original.approve("env-1", approval_id="approval-1", approver="operator:alice", now=NOW)
        original.authorize_execution(
            "env-1", execution_id="execute-1", actor="controller", meter=meter(), now=NOW
        )
        recovered = ControlSession.reconstruct_for_operator_resume(
            original.events,
            authorized_approvers=frozenset({"operator:alice"}),
            now=NOW + timedelta(minutes=6),
        )
        self.assertEqual(recovered.state, SessionState.SAFE_HOLD)
        self.assertEqual(recovered.proposal.proposal_id, "env-1")
        self.assertEqual(recovered.approval.approval_id, "approval-1")
        self.assertEqual(recovered.authorized_execution_count, 0)
        reconstruction = recovered.events[-1]
        self.assertEqual(reconstruction.event_type, "session_reconstructed")
        self.assertEqual(reconstruction.payload["retained_execution_authorizations"], 1)
        self.assertEqual(reconstruction.payload["replayed_execution_commands"], 0)
        self.assertTrue(reconstruction.payload["operator_resume_required"])
        self.assertTrue(reconstruction.payload["proposal_expired"])

    def test_replay_rejects_incomplete_duplicate_conflicting_and_bad_actor_histories(self):
        original = session()
        original.propose(proposal(), actor="planner", now=NOW)
        original.approve("env-1", approval_id="approval-1", approver="operator:alice", now=NOW)
        proposed, approved = original.events
        cases = (
            (proposed,),
            (proposed, proposed, approved),
            (
                proposed,
                replace(approved, payload={**approved.payload, "proposal_id": "other"}),
            ),
            (proposed, replace(approved, actor="intruder")),
        )
        for history in cases:
            with self.subTest(history=history):
                with self.assertRaises(HistoryReplayError):
                    ControlSession.reconstruct_for_operator_resume(
                        history,
                        authorized_approvers=frozenset({"operator:alice"}),
                        now=NOW + timedelta(seconds=1),
                    )

    def test_replay_rejects_bad_order_timestamp_and_duplicate_execution_id(self):
        original = session()
        original.propose(proposal(), actor="planner", now=NOW)
        original.approve("env-1", approval_id="approval-1", approver="operator:alice", now=NOW)
        original.authorize_execution(
            "env-1", execution_id="execute-1", actor="controller", meter=meter(), now=NOW
        )
        proposed, approved, execution = original.events
        histories = (
            (approved, proposed),
            (proposed, replace(approved, timestamp="not-a-time")),
            (proposed, approved, execution, execution),
            (proposed, replace(approved, timestamp=(NOW - timedelta(seconds=1)).isoformat())),
        )
        for history in histories:
            with self.subTest(history=history):
                with self.assertRaises(HistoryReplayError):
                    ControlSession.reconstruct_for_operator_resume(
                        history,
                        authorized_approvers=frozenset({"operator:alice"}),
                        now=NOW + timedelta(seconds=1),
                    )


if __name__ == "__main__":
    unittest.main()
