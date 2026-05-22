"use client";

import {
  ChangeEvent,
  KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { buildSlugIndex, FirmMemberLite } from "@/lib/api/comments";

interface Props {
  value: string;
  onChange: (next: string) => void;
  /** Firm members the user can mention. Already pre-filtered to
   *  members of the engagement's firm (the backend rejects others
   *  silently — the picker should only ever surface valid choices). */
  members: FirmMemberLite[];
  placeholder?: string;
  /** Hand back focus + reset when the parent submits. */
  rows?: number;
  /** Disable input — used when the user lacks comment permission. */
  disabled?: boolean;
  /** Optional submit-on-enter behaviour. Cmd/Ctrl+Enter submits;
   *  plain Enter inserts a newline. */
  onSubmit?: () => void;
  testId?: string;
}

interface SlugEntry {
  slug: string;
  user_id: string;
  full_name?: string;
}

/**
 * Textarea with an @-autocomplete dropdown that resolves to firm-
 * member slugs the W16/D2 backend parser understands.
 *
 * The picker fires when the user types ``@`` at the start of a word
 * (or after whitespace). It filters by slug prefix + full-name
 * substring so a typer who knows the partner's name but not the
 * slug still lands on the right pick. Selecting inserts
 * ``@slug ``; the trailing space matches how Slack / Linear / Notion
 * commit a mention so the next keystroke isn't part of the slug.
 *
 * No real-time presence + no rich-text — the W16/D3 hard rule says
 * functional, not polished. This is a controlled textarea, nothing
 * more.
 */
export default function MentionInput({
  value,
  onChange,
  members,
  placeholder,
  rows = 3,
  disabled = false,
  onSubmit,
  testId = "mention-input",
}: Props) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const [openAt, setOpenAt] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);

  // Slug index is keyed off ``members`` shape; rebuild only when
  // the member list itself changes.
  const slugs: SlugEntry[] = useMemo(() => buildSlugIndex(members), [members]);

  const filtered = useMemo(() => {
    if (!query) return slugs.slice(0, 8);
    const q = query.toLowerCase();
    return slugs
      .filter(
        (s) =>
          s.slug.startsWith(q) ||
          (s.full_name && s.full_name.toLowerCase().includes(q)),
      )
      .slice(0, 8);
  }, [slugs, query]);

  // Watch for "@" tokens after the cursor change. The picker opens
  // when the cursor is inside an @-token (no whitespace between @
  // and the cursor position).
  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    const next = e.target.value;
    onChange(next);
    const ta = e.target;
    const caret = ta.selectionStart ?? next.length;
    const upToCaret = next.slice(0, caret);
    const at = upToCaret.lastIndexOf("@");
    if (at === -1) {
      setOpenAt(null);
      return;
    }
    const between = upToCaret.slice(at + 1);
    // Trigger only if @ starts the text or follows whitespace, and
    // the chunk after @ contains no whitespace (i.e. we're still
    // inside the same token).
    const charBefore = at === 0 ? " " : upToCaret[at - 1] ?? "";
    if (/\s|^$/.test(charBefore) && !/\s/.test(between)) {
      setOpenAt(at);
      setQuery(between.toLowerCase());
      setHighlight(0);
    } else {
      setOpenAt(null);
    }
  };

  const insertMention = (entry: SlugEntry) => {
    if (openAt === null) return;
    const ta = taRef.current;
    if (!ta) return;
    const caret = ta.selectionStart ?? value.length;
    const before = value.slice(0, openAt);
    const after = value.slice(caret);
    const inserted = `@${entry.slug} `;
    const nextValue = `${before}${inserted}${after}`;
    onChange(nextValue);
    setOpenAt(null);
    setQuery("");
    // Move caret to the end of the inserted slug + space.
    queueMicrotask(() => {
      ta.focus();
      const pos = before.length + inserted.length;
      ta.setSelectionRange(pos, pos);
    });
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (openAt !== null && filtered.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => (h + 1) % filtered.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => (h - 1 + filtered.length) % filtered.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        insertMention(filtered[highlight]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setOpenAt(null);
        return;
      }
    }
    if (onSubmit && e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      onSubmit();
    }
  };

  // Keep the dropdown closed when the input loses focus — but defer
  // a tick so a click inside the dropdown still fires before close.
  const handleBlur = () => {
    setTimeout(() => setOpenAt(null), 100);
  };

  useEffect(() => {
    // If members list changes while the picker is open, reset
    // highlight so the cursor never lands past the end.
    setHighlight(0);
  }, [filtered.length]);

  return (
    <div style={{ position: "relative" }}>
      <textarea
        ref={taRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKey}
        onBlur={handleBlur}
        placeholder={placeholder}
        rows={rows}
        disabled={disabled}
        data-testid={testId}
        style={{
          width: "100%",
          padding: "8px 10px",
          fontFamily: "inherit",
          fontSize: 14,
          border: "1px solid #d0d4d9",
          borderRadius: 6,
          resize: "vertical",
          background: disabled ? "#f4f5f7" : "white",
        }}
      />
      {openAt !== null && filtered.length > 0 && (
        <ul
          data-testid="mention-dropdown"
          role="listbox"
          style={{
            position: "absolute",
            zIndex: 30,
            left: 0,
            right: 0,
            top: "100%",
            marginTop: 2,
            background: "white",
            border: "1px solid #d0d4d9",
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
            maxHeight: 200,
            overflowY: "auto",
            padding: 4,
            listStyle: "none",
          }}
        >
          {filtered.map((entry, i) => (
            <li
              key={entry.slug}
              role="option"
              aria-selected={i === highlight}
              data-testid={`mention-option-${entry.slug}`}
              onMouseDown={(ev) => {
                // onMouseDown beats onBlur in the event order, so the
                // click still fires before the dropdown closes.
                ev.preventDefault();
                insertMention(entry);
              }}
              onMouseEnter={() => setHighlight(i)}
              style={{
                padding: "6px 10px",
                fontSize: 13,
                borderRadius: 4,
                cursor: "pointer",
                background: i === highlight ? "#eef3ff" : "transparent",
                display: "flex",
                gap: 8,
              }}
            >
              <span style={{ fontWeight: 600 }}>@{entry.slug}</span>
              {entry.full_name && (
                <span style={{ color: "#6b7280" }}>— {entry.full_name}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
