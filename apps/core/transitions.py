"""
Centralised status-transition system.

Every state machine in the project is defined here as a TransitionGraph
instance.  Services import the appropriate instance and call .validate() —
no transition logic lives inside service methods.

State machines
──────────────
APPLICATION_TRANSITIONS
    Governs Application.status (managed by admins).

    ┌─────────────────────────────────────────────────────┐
    │                      PENDING                        │
    └──────┬──────────┬──────────────┬────────────────────┘
           │          │              │
        INTERVIEW  WAITLIST    APPROVED / REJECTED  ← terminal
           │    ╲  ╱    │
        APPROVED  ╳   INTERVIEW
        REJECTED  ╳   APPROVED
        WAITLIST  ╳   REJECTED

    From a player's perspective their application moves:
        pending  →  approved | rejected   (final outcomes they care about)
    Intermediate states (interview, waitlist) are admin-managed steps.

    Terminal states: approved, rejected — no further transitions permitted.

PLAYER_PROFILE_TRANSITIONS
    Governs PlayerProfile.status (managed by services on lifecycle events).

        free_agent  →  active
        active      →  free_agent | inactive | suspended
        inactive    →  active | free_agent
        suspended   →  inactive

    There are no terminal states — a suspended player can always recover
    to inactive, and an inactive player can become a free agent again.
"""

from apps.core.exceptions import InvalidStatusTransitionError


class TransitionGraph:
    """
    Immutable directed graph of allowed state transitions.

    Usage
    ─────
        graph = TransitionGraph("MyModel", {
            "draft":     {"published", "archived"},
            "published": {"archived"},
            "archived":  set(),  # terminal
        })

        graph.validate("draft", "published")   # OK — silent
        graph.validate("archived", "draft")    # raises InvalidStatusTransitionError
        graph.is_terminal("archived")          # True
        graph.allowed_targets("draft")         # frozenset({"published", "archived"})
    """

    def __init__(self, name: str, graph: dict[str, set[str]]) -> None:
        self.name = name
        # Freeze every value so the graph cannot be mutated after construction
        self._graph: dict[str, frozenset[str]] = {
            state: frozenset(targets) for state, targets in graph.items()
        }

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    @property
    def states(self) -> frozenset[str]:
        """All states registered in the graph."""
        return frozenset(self._graph)

    @property
    def terminal_states(self) -> frozenset[str]:
        """States from which no outgoing transition is allowed."""
        return frozenset(s for s, targets in self._graph.items() if not targets)

    def allowed_targets(self, from_state: str) -> frozenset[str]:
        """Return the set of states reachable from *from_state*."""
        return self._graph.get(from_state, frozenset())

    def is_terminal(self, state: str) -> bool:
        """Return True if *state* has no outgoing transitions."""
        return state in self.terminal_states

    def can_transition(self, from_state: str, to_state: str) -> bool:
        """Return True if the transition is explicitly permitted."""
        return to_state in self.allowed_targets(from_state)

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------

    def validate(self, from_state: str, to_state: str) -> None:
        """
        Assert that transitioning *from_state* → *to_state* is permitted.

        Raises:
            InvalidStatusTransitionError — with a descriptive message that
            lists allowed targets — when the transition is not in the graph.
        """
        if self.can_transition(from_state, to_state):
            return

        allowed = sorted(self.allowed_targets(from_state))
        if allowed:
            hint = f"Allowed from '{from_state}': {allowed}."
        else:
            hint = f"'{from_state}' is a terminal state — no further transitions are permitted."

        raise InvalidStatusTransitionError(
            f"[{self.name}] Cannot transition '{from_state}' → '{to_state}'. {hint}"
        )


# ---------------------------------------------------------------------------
# Application status transitions
# ---------------------------------------------------------------------------
#
# Covers both application types (captain, free_agent).
# From a player's perspective the path is:  pending → approved | rejected
# Admins can also route through:            pending → interview | waitlist
#
APPLICATION_TRANSITIONS = TransitionGraph(
    name="Application",
    graph={
        "pending": {
            "approved",
            "rejected",
            "waitlist",
            "interview",
        },
        "interview": {
            "approved",
            "rejected",
            "waitlist",
        },
        "waitlist": {
            "approved",
            "rejected",
            "interview",
        },
        "approved": set(),  # terminal — approval is irreversible
        "rejected": set(),  # terminal — rejection is irreversible
    },
)

# ---------------------------------------------------------------------------
# Player profile status transitions
# ---------------------------------------------------------------------------
#
# Drives the PlayerProfile.status lifecycle.
# No terminal states — suspended players can always recover to inactive.
#
PLAYER_PROFILE_TRANSITIONS = TransitionGraph(
    name="PlayerProfile",
    graph={
        "free_agent": {
            "active",
        },
        "active": {
            "free_agent",
            "inactive",
            "suspended",
        },
        "inactive": {
            "active",
            "free_agent",
        },
        "suspended": {
            "inactive",
        },
    },
)
