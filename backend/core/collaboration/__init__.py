"""Collaboration — engagement membership, assignment, and (W17/D2)
section ownership.

Distinct layer from firm membership (W5): firm membership says "you
belong to this firm"; engagement membership says "you're working on
this engagement, in this role".

Public surface:

  - :class:`EngagementRole` — the W17 role enum.
  - :class:`EngagementMember` — the service-layer result type.
  - :class:`MembershipResult` — uniform create/update/delete return.
  - :func:`assign_member` / :func:`change_member_role` /
    :func:`remove_member` / :func:`list_members` / :func:`get_lead` —
    the CRUD layer with W17/D1 invariants enforced.
"""

from .membership import (
    EngagementMember,
    MembershipResult,
    assign_member,
    change_member_role,
    ensure_creator_is_lead,
    get_lead,
    list_members,
    remove_member,
)
from .roles import EngagementRole

__all__ = [
    "EngagementMember",
    "EngagementRole",
    "MembershipResult",
    "assign_member",
    "change_member_role",
    "ensure_creator_is_lead",
    "get_lead",
    "list_members",
    "remove_member",
]
