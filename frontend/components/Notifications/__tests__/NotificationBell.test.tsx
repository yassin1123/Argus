import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api/notifications", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/notifications")>(
    "@/lib/api/notifications",
  );
  return { ...actual, getUnreadCount: vi.fn() };
});

import NotificationBell from "../NotificationBell";
import { getUnreadCount } from "@/lib/api/notifications";

const getUnreadMock = getUnreadCount as unknown as ReturnType<typeof vi.fn>;

describe("NotificationBell", () => {
  beforeEach(() => {
    getUnreadMock.mockReset();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the badge with the unread count from the API", async () => {
    getUnreadMock.mockResolvedValue({ user_id: "u-1", unread_count: 3 });
    render(<NotificationBell pollIntervalMs={1000} />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-bell-badge")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("notification-bell-badge").textContent).toBe("3");
    expect(screen.getByTestId("notification-bell").getAttribute("data-unread-count")).toBe("3");
  });

  it("hides the badge when there are zero unread", async () => {
    getUnreadMock.mockResolvedValue({ user_id: "u-1", unread_count: 0 });
    render(<NotificationBell pollIntervalMs={1000} />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-bell").getAttribute("data-unread-count")).toBe("0"),
    );
    expect(screen.queryByTestId("notification-bell-badge")).toBeNull();
  });

  it("collapses counts > 99 to '99+'", async () => {
    getUnreadMock.mockResolvedValue({ user_id: "u-1", unread_count: 142 });
    render(<NotificationBell pollIntervalMs={1000} />);
    await waitFor(() =>
      expect(screen.getByTestId("notification-bell-badge")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("notification-bell-badge").textContent).toBe("99+");
  });

  it("polls on the configured interval", async () => {
    getUnreadMock
      .mockResolvedValueOnce({ user_id: "u-1", unread_count: 1 })
      .mockResolvedValueOnce({ user_id: "u-1", unread_count: 2 })
      .mockResolvedValueOnce({ user_id: "u-1", unread_count: 5 });
    render(<NotificationBell pollIntervalMs={500} />);

    await waitFor(() =>
      expect(screen.getByTestId("notification-bell-badge").textContent).toBe("1"),
    );

    // Tick forward — should re-poll.
    vi.advanceTimersByTime(500);
    await waitFor(() =>
      expect(screen.getByTestId("notification-bell-badge").textContent).toBe("2"),
    );
    vi.advanceTimersByTime(500);
    await waitFor(() =>
      expect(screen.getByTestId("notification-bell-badge").textContent).toBe("5"),
    );
  });

  it("fires onClick when clicked", async () => {
    getUnreadMock.mockResolvedValue({ user_id: "u-1", unread_count: 0 });
    const onClick = vi.fn();
    render(<NotificationBell pollIntervalMs={1000} onClick={onClick} />);
    fireEvent.click(screen.getByTestId("notification-bell"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
