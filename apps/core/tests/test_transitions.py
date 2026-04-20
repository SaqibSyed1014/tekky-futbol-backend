"""
Unit tests for the TransitionGraph state machine.

Tests cover both the generic TransitionGraph API and the two concrete
instances used in the project:
    - APPLICATION_TRANSITIONS
    - PLAYER_PROFILE_TRANSITIONS
"""
from django.test import SimpleTestCase

from apps.core.exceptions import InvalidStatusTransitionError
from apps.core.transitions import (
    APPLICATION_TRANSITIONS,
    PLAYER_PROFILE_TRANSITIONS,
    TransitionGraph,
)


# ===========================================================================
# TransitionGraph — generic API
# ===========================================================================


class TransitionGraphStatesTest(SimpleTestCase):
    """Tests for .states, .terminal_states, .is_terminal, .allowed_targets."""

    def setUp(self):
        self.graph = TransitionGraph(
            name="TestModel",
            graph={
                "draft":     {"published", "archived"},
                "published": {"archived"},
                "archived":  set(),  # terminal
            },
        )

    def test_states_returns_all_defined_states(self):
        self.assertEqual(
            self.graph.states,
            frozenset({"draft", "published", "archived"}),
        )

    def test_terminal_states_returns_states_with_no_outgoing(self):
        self.assertEqual(self.graph.terminal_states, frozenset({"archived"}))

    def test_is_terminal_true_for_terminal_state(self):
        self.assertTrue(self.graph.is_terminal("archived"))

    def test_is_terminal_false_for_non_terminal_state(self):
        self.assertFalse(self.graph.is_terminal("draft"))
        self.assertFalse(self.graph.is_terminal("published"))

    def test_allowed_targets_returns_correct_set(self):
        self.assertEqual(
            self.graph.allowed_targets("draft"),
            frozenset({"published", "archived"}),
        )

    def test_allowed_targets_for_terminal_returns_empty_frozenset(self):
        self.assertEqual(self.graph.allowed_targets("archived"), frozenset())

    def test_allowed_targets_for_unknown_state_returns_empty_frozenset(self):
        self.assertEqual(self.graph.allowed_targets("nonexistent"), frozenset())


class TransitionGraphCanTransitionTest(SimpleTestCase):
    """Tests for .can_transition()."""

    def setUp(self):
        self.graph = TransitionGraph(
            name="TestModel",
            graph={
                "draft":     {"published", "archived"},
                "published": {"archived"},
                "archived":  set(),
            },
        )

    def test_returns_true_for_valid_transition(self):
        self.assertTrue(self.graph.can_transition("draft", "published"))
        self.assertTrue(self.graph.can_transition("draft", "archived"))
        self.assertTrue(self.graph.can_transition("published", "archived"))

    def test_returns_false_for_invalid_forward_transition(self):
        self.assertFalse(self.graph.can_transition("archived", "draft"))

    def test_returns_false_for_self_transition(self):
        self.assertFalse(self.graph.can_transition("draft", "draft"))

    def test_returns_false_for_terminal_to_any_state(self):
        self.assertFalse(self.graph.can_transition("archived", "published"))
        self.assertFalse(self.graph.can_transition("archived", "archived"))

    def test_returns_false_for_unknown_from_state(self):
        self.assertFalse(self.graph.can_transition("ghost", "draft"))


class TransitionGraphValidateTest(SimpleTestCase):
    """Tests for .validate() — should raise on illegal transitions."""

    def setUp(self):
        self.graph = TransitionGraph(
            name="TestModel",
            graph={
                "draft":     {"published"},
                "published": set(),  # terminal
            },
        )

    def test_valid_transition_does_not_raise(self):
        # Should complete silently
        self.graph.validate("draft", "published")

    def test_invalid_transition_raises_invalid_status_transition_error(self):
        with self.assertRaises(InvalidStatusTransitionError):
            self.graph.validate("published", "draft")

    def test_terminal_state_raises_with_descriptive_message(self):
        with self.assertRaises(InvalidStatusTransitionError) as ctx:
            self.graph.validate("published", "draft")
        self.assertIn("terminal", str(ctx.exception).lower())

    def test_invalid_non_terminal_raises_with_allowed_hint(self):
        """
        When transitioning FROM a non-terminal state that has allowed targets,
        the error message should list those targets (not the "terminal" hint).
        """
        graph = TransitionGraph(
            "M",
            {"a": {"b"}, "b": {"c"}, "c": set()},
        )
        # "b" → "a" is invalid but "b" is non-terminal (has target "c")
        with self.assertRaises(InvalidStatusTransitionError) as ctx:
            graph.validate("b", "a")
        msg = str(ctx.exception)
        # Should mention the allowed target, not the "terminal" hint
        self.assertIn("b", msg)
        self.assertIn("a", msg)

    def test_error_message_contains_graph_name(self):
        with self.assertRaises(InvalidStatusTransitionError) as ctx:
            self.graph.validate("published", "draft")
        self.assertIn("TestModel", str(ctx.exception))

    def test_error_message_mentions_from_and_to_states(self):
        with self.assertRaises(InvalidStatusTransitionError) as ctx:
            self.graph.validate("published", "draft")
        msg = str(ctx.exception)
        self.assertIn("published", msg)
        self.assertIn("draft", msg)


class TransitionGraphImmutabilityTest(SimpleTestCase):
    """The graph must be immutable — construction freezes all target sets."""

    def test_mutating_original_dict_does_not_affect_graph(self):
        original = {"a": {"b"}, "b": set()}
        graph = TransitionGraph("M", original)
        original["a"].add("c")  # mutate original set
        # Graph must not be affected
        self.assertNotIn("c", graph.allowed_targets("a"))

    def test_allowed_targets_returns_frozenset(self):
        graph = TransitionGraph("M", {"a": {"b"}, "b": set()})
        result = graph.allowed_targets("a")
        self.assertIsInstance(result, frozenset)

    def test_states_returns_frozenset(self):
        graph = TransitionGraph("M", {"a": {"b"}, "b": set()})
        self.assertIsInstance(graph.states, frozenset)

    def test_terminal_states_returns_frozenset(self):
        graph = TransitionGraph("M", {"a": {"b"}, "b": set()})
        self.assertIsInstance(graph.terminal_states, frozenset)


# ===========================================================================
# APPLICATION_TRANSITIONS — concrete instance
# ===========================================================================


class ApplicationTransitionsTest(SimpleTestCase):
    """Tests specific to the APPLICATION_TRANSITIONS state machine."""

    graph = APPLICATION_TRANSITIONS

    def test_pending_can_transition_to_approved(self):
        self.assertTrue(self.graph.can_transition("pending", "approved"))

    def test_pending_can_transition_to_rejected(self):
        self.assertTrue(self.graph.can_transition("pending", "rejected"))

    def test_pending_can_transition_to_interview(self):
        self.assertTrue(self.graph.can_transition("pending", "interview"))

    def test_pending_can_transition_to_waitlist(self):
        self.assertTrue(self.graph.can_transition("pending", "waitlist"))

    def test_interview_can_transition_to_approved(self):
        self.assertTrue(self.graph.can_transition("interview", "approved"))

    def test_interview_can_transition_to_rejected(self):
        self.assertTrue(self.graph.can_transition("interview", "rejected"))

    def test_interview_can_transition_to_waitlist(self):
        self.assertTrue(self.graph.can_transition("interview", "waitlist"))

    def test_waitlist_can_transition_to_approved(self):
        self.assertTrue(self.graph.can_transition("waitlist", "approved"))

    def test_waitlist_can_transition_to_rejected(self):
        self.assertTrue(self.graph.can_transition("waitlist", "rejected"))

    def test_waitlist_can_transition_to_interview(self):
        self.assertTrue(self.graph.can_transition("waitlist", "interview"))

    def test_approved_is_terminal(self):
        self.assertTrue(self.graph.is_terminal("approved"))

    def test_rejected_is_terminal(self):
        self.assertTrue(self.graph.is_terminal("rejected"))

    def test_pending_is_not_terminal(self):
        self.assertFalse(self.graph.is_terminal("pending"))

    def test_approved_cannot_transition_anywhere(self):
        for target in ("pending", "rejected", "waitlist", "interview"):
            self.assertFalse(
                self.graph.can_transition("approved", target),
                f"approved → {target} must be forbidden",
            )

    def test_rejected_cannot_transition_anywhere(self):
        for target in ("pending", "approved", "waitlist", "interview"):
            self.assertFalse(
                self.graph.can_transition("rejected", target),
                f"rejected → {target} must be forbidden",
            )

    def test_pending_cannot_transition_to_pending(self):
        self.assertFalse(self.graph.can_transition("pending", "pending"))

    def test_terminal_states_are_approved_and_rejected(self):
        self.assertEqual(
            self.graph.terminal_states,
            frozenset({"approved", "rejected"}),
        )

    def test_validate_raises_for_approved_to_pending(self):
        with self.assertRaises(InvalidStatusTransitionError):
            self.graph.validate("approved", "pending")

    def test_validate_raises_for_rejected_to_pending(self):
        with self.assertRaises(InvalidStatusTransitionError):
            self.graph.validate("rejected", "pending")


# ===========================================================================
# PLAYER_PROFILE_TRANSITIONS — concrete instance
# ===========================================================================


class PlayerProfileTransitionsTest(SimpleTestCase):
    """Tests specific to the PLAYER_PROFILE_TRANSITIONS state machine."""

    graph = PLAYER_PROFILE_TRANSITIONS

    def test_free_agent_can_transition_to_active(self):
        self.assertTrue(self.graph.can_transition("free_agent", "active"))

    def test_active_can_transition_to_free_agent(self):
        self.assertTrue(self.graph.can_transition("active", "free_agent"))

    def test_active_can_transition_to_inactive(self):
        self.assertTrue(self.graph.can_transition("active", "inactive"))

    def test_active_can_transition_to_suspended(self):
        self.assertTrue(self.graph.can_transition("active", "suspended"))

    def test_inactive_can_transition_to_active(self):
        self.assertTrue(self.graph.can_transition("inactive", "active"))

    def test_inactive_can_transition_to_free_agent(self):
        self.assertTrue(self.graph.can_transition("inactive", "free_agent"))

    def test_suspended_can_transition_to_inactive(self):
        self.assertTrue(self.graph.can_transition("suspended", "inactive"))

    def test_suspended_cannot_transition_to_active(self):
        self.assertFalse(self.graph.can_transition("suspended", "active"))

    def test_suspended_cannot_transition_to_free_agent(self):
        self.assertFalse(self.graph.can_transition("suspended", "free_agent"))

    def test_free_agent_cannot_transition_to_suspended(self):
        self.assertFalse(self.graph.can_transition("free_agent", "suspended"))

    def test_free_agent_cannot_transition_to_inactive(self):
        self.assertFalse(self.graph.can_transition("free_agent", "inactive"))

    def test_no_terminal_states(self):
        """Player profile has no terminal states — every player can recover."""
        self.assertEqual(self.graph.terminal_states, frozenset())

    def test_all_states_present(self):
        self.assertEqual(
            self.graph.states,
            frozenset({"free_agent", "active", "inactive", "suspended"}),
        )

    def test_validate_raises_for_suspended_to_active(self):
        with self.assertRaises(InvalidStatusTransitionError):
            self.graph.validate("suspended", "active")

    def test_validate_raises_for_free_agent_to_inactive(self):
        with self.assertRaises(InvalidStatusTransitionError):
            self.graph.validate("free_agent", "inactive")
