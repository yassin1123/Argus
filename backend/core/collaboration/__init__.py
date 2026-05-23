"""Collaboration — engagement membership (W17/D1) + section
ownership / work-status (W17/D2).

Distinct layer from firm membership (W5): firm membership says "you
belong to this firm"; engagement membership says "you're working on
this engagement, in this role"; section assignment says "you own
this section's work".

Public surface:

  W17/D1:
    - :class:`EngagementRole`, :class:`EngagementMember`,
      :class:`MembershipResult`.
    - :func:`assign_member` / :func:`change_member_role` /
      :func:`remove_member` / :func:`list_members` /
      :func:`get_lead` / :func:`ensure_creator_is_lead`.

  W17/D2:
    - :class:`SectionStatus`, :class:`SectionAssignment`,
      :class:`AssignmentResult`.
    - :func:`assign_section` / :func:`set_section_status` /
      :func:`unassign_section` / :func:`list_section_assignments` /
      :func:`get_sections_owned_by`.
    - :class:`CoverageMap`, :class:`CoverageEntry`,
      :func:`section_coverage`.
"""

from .coverage import CoverageEntry, CoverageMap, section_coverage
from .explicit_tasks import (
    ExplicitTask,
    TaskResult,
    complete_task,
    create_task,
    list_open_tasks_for_user,
    list_tasks_for_session,
)
from .my_work import MyWork, UnifiedTask, get_my_work
from .tasks import DerivedTask, derive_tasks_for_user
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
from .section_assignments import (
    AssignmentResult,
    SectionAssignment,
    assign_section,
    get_sections_owned_by,
    list_section_assignments,
    set_section_status,
    unassign_section,
)
from .section_status import SectionStatus, TRACKABLE_SECTION_PATHS

__all__ = [
    "AssignmentResult",
    "CoverageEntry",
    "CoverageMap",
    "DerivedTask",
    "EngagementMember",
    "EngagementRole",
    "ExplicitTask",
    "MembershipResult",
    "MyWork",
    "SectionAssignment",
    "SectionStatus",
    "TRACKABLE_SECTION_PATHS",
    "TaskResult",
    "UnifiedTask",
    "assign_member",
    "assign_section",
    "change_member_role",
    "complete_task",
    "create_task",
    "derive_tasks_for_user",
    "ensure_creator_is_lead",
    "get_lead",
    "get_my_work",
    "get_sections_owned_by",
    "list_members",
    "list_open_tasks_for_user",
    "list_section_assignments",
    "list_tasks_for_session",
    "remove_member",
    "section_coverage",
    "set_section_status",
    "unassign_section",
]
