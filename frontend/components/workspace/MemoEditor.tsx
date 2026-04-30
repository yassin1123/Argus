"use client";

import { useEditor, EditorContent, Mark, mergeAttributes } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect, useMemo, useRef, useState } from "react";

import StatusPill from "@/components/ui/StatusPill";
import { useToast } from "@/components/ui/Toast";
import {
  exportArtifactDocx,
  getArtifact,
  patchArtifact,
} from "@/lib/api";
import type { Artifact, ArtifactStatus } from "@/lib/types";

// ---- Custom citation mark (renders inline `[N]` chip) ------------------

const Citation = Mark.create({
  name: "citation",

  addAttributes() {
    return {
      n: { default: 1 },
      chunk_ids: { default: [] as string[] },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-citation]" }];
  },

  renderHTML({ HTMLAttributes, mark }) {
    const cids = (mark.attrs.chunk_ids as string[]) || [];
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-citation": "true",
        "data-chunk-ids": cids.join(","),
        class: "argus-cite-mark",
      }),
      0,
    ];
  },
});

// ---- Helpers: outline + citation extraction ----------------------------

interface PMNode {
  type?: string;
  attrs?: Record<string, unknown>;
  marks?: Array<{ type?: string; attrs?: Record<string, unknown> }>;
  content?: PMNode[];
  text?: string;
}

interface OutlineEntry {
  id: string;
  level: number;
  text: string;
}

function plainText(node: PMNode): string {
  if (node.text) return node.text;
  if (!node.content) return "";
  return node.content.map(plainText).join("");
}

function extractOutline(doc: PMNode | null): OutlineEntry[] {
  if (!doc?.content) return [];
  const out: OutlineEntry[] = [];
  let i = 0;
  for (const node of doc.content) {
    if (node.type === "heading") {
      const level = (node.attrs?.level as number) || 2;
      const text = plainText(node).trim();
      if (text) out.push({ id: `h-${i}`, level, text });
    }
    i += 1;
  }
  return out;
}

function extractCitedChunkIds(doc: PMNode | null): string[] {
  if (!doc) return [];
  const seen = new Set<string>();
  const walk = (node: PMNode) => {
    if (node.marks) {
      for (const m of node.marks) {
        if (m.type === "citation") {
          const cids = m.attrs?.chunk_ids;
          if (Array.isArray(cids)) for (const c of cids) if (typeof c === "string") seen.add(c);
        }
      }
    }
    if (node.content) for (const c of node.content) walk(c);
  };
  walk(doc);
  return Array.from(seen);
}

// ---- Editor -------------------------------------------------------------

const STARTER_DOC = { type: "doc", content: [{ type: "paragraph" }] };

export default function MemoEditor({
  artifactId,
  onClose,
}: {
  artifactId: string;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [lastSaved, setLastSaved] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [docVersion, setDocVersion] = useState(0);
  const [slashMenu, setSlashMenu] = useState<{ x: number; y: number } | null>(null);
  const editorContainerRef = useRef<HTMLDivElement | null>(null);

  const editor = useEditor({
    extensions: [StarterKit, Citation],
    content: STARTER_DOC,
    editorProps: {
      attributes: {
        class:
          "prose prose-sm max-w-none p-6 font-serif text-[14px] leading-relaxed text-argus-primary focus:outline-none [&_h1]:font-serif [&_h2]:font-serif [&_h3]:font-serif [&_h1]:text-[24px] [&_h2]:text-[18px] [&_h3]:text-[15px]",
      },
      handleKeyDown(_view, event) {
        if (event.key === "/") {
          // Defer so the "/" character renders before the menu opens.
          requestAnimationFrame(() => {
            const rect = editorContainerRef.current?.getBoundingClientRect();
            if (!rect) return;
            const sel = window.getSelection();
            if (!sel || sel.rangeCount === 0) return;
            const r = sel.getRangeAt(0).getBoundingClientRect();
            setSlashMenu({ x: r.left - rect.left, y: r.bottom - rect.top + 4 });
          });
          return false;
        }
        if (event.key === "Escape" && slashMenu) {
          setSlashMenu(null);
          return true;
        }
        return false;
      },
    },
    onUpdate: () => setDocVersion((v) => v + 1),
    immediatelyRender: false,
  });

  // Load artifact
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const a = await getArtifact(artifactId);
        if (!alive) return;
        setArtifact(a);
        setTitle(a.title);
        if (editor && a.document_json) {
          editor.commands.setContent(a.document_json as Record<string, unknown>);
          setDocVersion((v) => v + 1);
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "Failed to load");
      }
    })();
    return () => {
      alive = false;
    };
  }, [artifactId, editor]);

  // Outline + citations derived from current document
  const { outline, citedIds } = useMemo(() => {
    void docVersion; // re-compute when doc changes
    const json = editor?.getJSON() as PMNode | undefined;
    return {
      outline: extractOutline(json ?? null),
      citedIds: extractCitedChunkIds(json ?? null),
    };
  }, [editor, docVersion]);

  const handleSave = async () => {
    if (!editor || !artifact) return;
    setSaving(true);
    setError(null);
    try {
      const doc = editor.getJSON();
      const updated = await patchArtifact(artifact.id, {
        title: title || artifact.title,
        document_json: doc,
      });
      setArtifact(updated);
      setLastSaved(new Date().toLocaleTimeString());
      toast("Memo saved.", { variant: "success", durationMs: 2000 });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Save failed";
      setError(msg);
      toast(msg, { variant: "error" });
    } finally {
      setSaving(false);
    }
  };

  const handleStatusChange = async (next: ArtifactStatus) => {
    if (!artifact) return;
    try {
      const updated = await patchArtifact(artifact.id, { status: next });
      setArtifact(updated);
      toast(`Status changed to ${next}.`, { variant: "info", durationMs: 2000 });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to change status";
      setError(msg);
      toast(msg, { variant: "error" });
    }
  };

  const handleExport = async () => {
    if (!artifact) return;
    setExporting(true);
    setError(null);
    try {
      const blob = await exportArtifactDocx(artifact.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${artifact.title.replace(/[^\w\s.-]/g, "_").slice(0, 60)}.docx`;
      link.click();
      URL.revokeObjectURL(url);
      toast("DOCX exported.", { variant: "success", durationMs: 2000 });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Export failed";
      setError(msg);
      toast(msg, { variant: "error" });
    } finally {
      setExporting(false);
    }
  };

  // Slash-menu commands
  const slashCommands: Array<{ label: string; hint: string; run: () => void }> = useMemo(() => {
    if (!editor) return [];
    const removeSlash = () => {
      // Remove the literal "/" the user typed before invoking the command.
      const { from } = editor.state.selection;
      if (from > 0) editor.chain().focus().setTextSelection({ from: from - 1, to: from }).deleteSelection().run();
    };
    return [
      {
        label: "Heading 1",
        hint: "Section title",
        run: () => {
          removeSlash();
          editor.chain().focus().toggleHeading({ level: 1 }).run();
          setSlashMenu(null);
        },
      },
      {
        label: "Heading 2",
        hint: "Subsection",
        run: () => {
          removeSlash();
          editor.chain().focus().toggleHeading({ level: 2 }).run();
          setSlashMenu(null);
        },
      },
      {
        label: "Heading 3",
        hint: "Inline subhead",
        run: () => {
          removeSlash();
          editor.chain().focus().toggleHeading({ level: 3 }).run();
          setSlashMenu(null);
        },
      },
      {
        label: "Bullet list",
        hint: "• item",
        run: () => {
          removeSlash();
          editor.chain().focus().toggleBulletList().run();
          setSlashMenu(null);
        },
      },
      {
        label: "Numbered list",
        hint: "1. item",
        run: () => {
          removeSlash();
          editor.chain().focus().toggleOrderedList().run();
          setSlashMenu(null);
        },
      },
      {
        label: "Quote",
        hint: "Pull quote",
        run: () => {
          removeSlash();
          editor.chain().focus().toggleBlockquote().run();
          setSlashMenu(null);
        },
      },
      {
        label: "Citation placeholder",
        hint: "Insert [?] for later",
        run: () => {
          removeSlash();
          editor
            .chain()
            .focus()
            .insertContent({
              type: "text",
              text: "[?]",
              marks: [{ type: "citation", attrs: { n: 0, chunk_ids: [] } }],
            })
            .run();
          setSlashMenu(null);
        },
      },
    ];
  }, [editor]);

  if (error && !artifact) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <p className="text-argus-contested">{error}</p>
          <button onClick={onClose} className="mt-3 text-[12px] text-argus-accent hover:underline">
            ← Back
          </button>
        </div>
      </div>
    );
  }

  if (!artifact) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-[12px] text-argus-tertiary">Loading memo…</p>
      </div>
    );
  }

  return (
    <section className="flex h-full flex-col bg-canvas">
      {/* Header */}
      <header className="flex flex-wrap items-center gap-3 border-b border-argus-border-subtle bg-surface px-5 py-3">
        <button
          type="button"
          onClick={onClose}
          className="text-[11px] text-argus-tertiary hover:text-argus-primary"
        >
          ← Back to engagement
        </button>
        <span className="h-3 w-px bg-argus-border-subtle" />
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => void handleSave()}
          className="min-w-0 flex-1 bg-transparent font-serif text-[16px] font-semibold text-argus-primary focus:outline-none"
        />

        <StatusPill status={artifact.status} />
        <select
          value={artifact.status}
          onChange={(e) => void handleStatusChange(e.target.value as ArtifactStatus)}
          aria-label="Change artifact status"
          className="rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 text-[10px] uppercase tracking-wide text-argus-secondary focus:outline-none"
        >
          <option value="draft">Draft</option>
          <option value="review">Review</option>
          <option value="final">Final</option>
        </select>

        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving}
          className="rounded-sm border border-argus-border-moderate bg-surface px-2.5 py-1 text-[11px] font-medium text-argus-secondary hover:border-argus-primary hover:text-argus-primary disabled:opacity-50"
        >
          {saving ? "Saving…" : lastSaved ? `Saved ${lastSaved}` : "Save"}
        </button>
        <button
          type="button"
          onClick={() => void handleExport()}
          disabled={exporting}
          className="rounded-sm border border-argus-border-strong bg-argus-primary px-2.5 py-1 text-[11px] font-semibold text-argus-inverse hover:opacity-90 disabled:opacity-50"
        >
          {exporting ? "Exporting…" : "Export DOCX"}
        </button>
      </header>

      {error ? (
        <p className="border-b border-argus-contested-border bg-argus-contested-bg px-5 py-2 text-[12px] text-argus-contested">
          {error}
        </p>
      ) : null}

      {/* Body: outline rail + editor */}
      <div className="flex flex-1 overflow-hidden">
        {/* Outline rail */}
        <aside className="hidden w-56 shrink-0 overflow-y-auto border-r border-argus-border-subtle bg-[var(--bg-rail)] py-4 lg:block">
          <div className="argus-label mb-2 px-4">Outline</div>
          {outline.length === 0 ? (
            <p className="px-4 text-[11px] leading-snug text-argus-tertiary">
              Add headings (H1 / H2 / H3) to build a navigable outline.
            </p>
          ) : (
            <ul className="text-[12px]">
              {outline.map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    className="block w-full truncate px-4 py-1 text-left text-argus-secondary hover:bg-elevated hover:text-argus-primary"
                    style={{ paddingLeft: `${(entry.level - 1) * 12 + 16}px` }}
                    title={entry.text}
                    onClick={() => {
                      if (!editorContainerRef.current) return;
                      const headings = Array.from(
                        editorContainerRef.current.querySelectorAll<HTMLElement>("h1, h2, h3"),
                      );
                      const target = headings.find(
                        (h) => (h.textContent || "").trim() === entry.text,
                      );
                      target?.scrollIntoView({ behavior: "smooth", block: "start" });
                    }}
                  >
                    <span
                      className={
                        entry.level === 1
                          ? "font-serif font-semibold"
                          : entry.level === 2
                            ? "font-serif"
                            : "text-argus-tertiary"
                      }
                    >
                      {entry.text}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="argus-label mb-2 mt-6 px-4">Citations</div>
          <div className="px-4 text-[11px] leading-snug text-argus-tertiary">
            {citedIds.length === 0 ? (
              <span>No citations in this draft yet.</span>
            ) : (
              <span>
                <span className="font-mono tabular-nums text-argus-primary">{citedIds.length}</span>{" "}
                unique chunk{citedIds.length === 1 ? "" : "s"} cited.
              </span>
            )}
          </div>
        </aside>

        {/* Editor + slash menu */}
        <div className="flex-1 overflow-y-auto bg-canvas">
          <div className="mx-auto max-w-[760px] py-6">
            <article
              ref={editorContainerRef}
              className="relative border border-argus-border-subtle bg-surface shadow-argus-sm"
            >
              <EditorContent editor={editor} />

              {slashMenu ? (
                <div
                  role="menu"
                  className="absolute z-30 w-56 rounded-sm border border-argus-border-moderate bg-surface text-[12px] shadow-popover"
                  style={{ left: slashMenu.x, top: slashMenu.y }}
                  onMouseDown={(e) => e.preventDefault()}
                >
                  <div className="border-b border-argus-border-subtle px-2 py-1">
                    <span className="argus-label">Insert</span>
                  </div>
                  <ul>
                    {slashCommands.map((c) => (
                      <li key={c.label}>
                        <button
                          type="button"
                          onClick={c.run}
                          className="flex w-full items-center justify-between gap-3 px-2 py-1 text-left hover:bg-elevated"
                        >
                          <span className="text-argus-primary">{c.label}</span>
                          <span className="font-mono text-[10px] text-argus-tertiary">{c.hint}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <div className="border-t border-argus-border-subtle px-2 py-1 text-[10px] text-argus-tertiary">
                    Esc to dismiss
                  </div>
                </div>
              ) : null}
            </article>

            {/* Citations footer */}
            <footer className="mt-3 flex items-center justify-between border border-argus-border-subtle bg-surface px-4 py-2 text-[11px]">
              <span className="argus-label">Citations</span>
              <span className="font-mono tabular-nums text-argus-tertiary">
                {citedIds.length} unique chunk{citedIds.length === 1 ? "" : "s"} cited
              </span>
            </footer>
          </div>
        </div>
      </div>
    </section>
  );
}
