import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import MentionInput from "../MentionInput";

const MEMBERS = [
  { user_id: "u-alex", email: "alex.chen@meridian.invalid", full_name: "Alex Chen" },
  { user_id: "u-sarah", email: "sarah.kim@meridian.invalid", full_name: "Sarah Kim" },
  { user_id: "u-kira", email: "kira.lee@meridian.invalid", full_name: "Kira Lee" },
];

describe("MentionInput", () => {
  it("opens the autocomplete dropdown when the user types @", () => {
    const onChange = vi.fn();
    render(
      <MentionInput value="" onChange={onChange} members={MEMBERS} />,
    );
    const ta = screen.getByTestId("mention-input") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "@" } });
    expect(screen.getByTestId("mention-dropdown")).toBeInTheDocument();
    expect(screen.getByTestId("mention-option-alex.chen")).toBeInTheDocument();
    expect(screen.getByTestId("mention-option-sarah.kim")).toBeInTheDocument();
  });

  it("filters the dropdown as the user types a slug prefix", () => {
    let v = "";
    const onChange = vi.fn((next: string) => {
      v = next;
    });
    const { rerender } = render(
      <MentionInput value={v} onChange={onChange} members={MEMBERS} />,
    );
    const ta = screen.getByTestId("mention-input") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "@sar" } });
    rerender(<MentionInput value={v} onChange={onChange} members={MEMBERS} />);
    expect(screen.getByTestId("mention-option-sarah.kim")).toBeInTheDocument();
    expect(screen.queryByTestId("mention-option-alex.chen")).toBeNull();
  });

  it("inserts the chosen slug into the textarea on mousedown", () => {
    let v = "";
    const onChange = vi.fn((next: string) => {
      v = next;
    });
    const { rerender } = render(
      <MentionInput value={v} onChange={onChange} members={MEMBERS} />,
    );
    const ta = screen.getByTestId("mention-input") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "Hey @sar" } });
    rerender(<MentionInput value={v} onChange={onChange} members={MEMBERS} />);
    const opt = screen.getByTestId("mention-option-sarah.kim");
    fireEvent.mouseDown(opt);
    expect(onChange).toHaveBeenLastCalledWith("Hey @sarah.kim ");
  });

  it("does NOT trigger the dropdown when @ follows a non-space character", () => {
    const onChange = vi.fn();
    render(
      <MentionInput value="" onChange={onChange} members={MEMBERS} />,
    );
    const ta = screen.getByTestId("mention-input") as HTMLTextAreaElement;
    // "email@" looks like the start of an email — the parser must not
    // misread it as a mention. This matches the backend regex's
    // "must follow whitespace or start" rule.
    fireEvent.change(ta, { target: { value: "email@" } });
    expect(screen.queryByTestId("mention-dropdown")).toBeNull();
  });
});
