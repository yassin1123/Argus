// Notification → URL deep-link mapper — Phase 4 / Week 18 / Day 4.
//
// Pure function: takes a NotificationRow + maps to the workspace URL
// the click should route to, with query parameters / hash that the
// destination component reads to open the right panel.
//
// URL contract (read by the workspace shell):
//
//   ?openComment={comment_id}    → opens W16 ThreadPanel scrolled to comment
//   ?openReview=1                → opens the W15 review panel
//   ?openTask={task_id}          → highlights the task on /my-work
//   #section-{section_path}      → scrolls to the section (W17 overlay)
//   #comment-{comment_id}        → scrolls to the comment row
//
// We pick exactly one anchor / query per notification type so the
// destination shell knows unambiguously which surface to focus.

import type { NotificationRow } from "@/lib/api/notifications";

export interface DeepLink {
  /** Next.js href the bell / feed pushes to. */
  href: string;
  /** Optional aria-label override for the click target. */
  ariaLabel?: string;
}

const _sref = (n: NotificationRow): Record<string, unknown> =>
  (n.source_ref || {}) as Record<string, unknown>;

export function notificationDeepLink(n: NotificationRow): DeepLink {
  const sref = _sref(n);
  const sid = n.session_id;

  switch (n.notification_type) {
    case "mention":
    case "comment_reply": {
      const commentId = sref.comment_id as string | undefined;
      if (sid && commentId) {
        return {
          href: `/sessions/${sid}?openComment=${encodeURIComponent(commentId)}#comment-${encodeURIComponent(commentId)}`,
          ariaLabel: "Open comment thread",
        };
      }
      return { href: sid ? `/sessions/${sid}` : "/" };
    }
    case "review_requested":
    case "changes_requested":
    case "review_approved": {
      if (sid) {
        return {
          href: `/sessions/${sid}?openReview=1`,
          ariaLabel: "Open review panel",
        };
      }
      return { href: "/" };
    }
    case "section_assigned":
    case "section_needs_review": {
      const sp = sref.section_path as string | undefined;
      if (sid && sp) {
        return {
          href: `/sessions/${sid}#section-${encodeURIComponent(sp)}`,
          ariaLabel: `Open section ${sp}`,
        };
      }
      return { href: sid ? `/sessions/${sid}` : "/" };
    }
    case "engagement_assigned": {
      return { href: sid ? `/sessions/${sid}` : "/" };
    }
    case "task_assigned": {
      const taskId = sref.task_id as string | undefined;
      // My-work dashboard is on the home page (W17/D4 mount).
      const base = "/";
      if (taskId) {
        return {
          href: `${base}?openTask=${encodeURIComponent(taskId)}`,
          ariaLabel: "Open task",
        };
      }
      return { href: base };
    }
  }

  // Defensive default — unknown type lands on the home page.
  return { href: "/" };
}
