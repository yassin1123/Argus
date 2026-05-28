"use client";

// Per-artifact quality rating — Phase 5 / Week 24 / Day 3.
// A quick prompt shown after a consultant downloads/approves an
// artifact: 1-5 stars + an optional comment. Dismissable — never
// mandatory.

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { postArtifactRating } from "@/lib/api/pilotFeedback";

interface Props {
  sessionId: string;
  artifactId?: string;
  artifactType?: string;
  onClose: () => void;
}

export default function ArtifactRatingPrompt({
  sessionId,
  artifactId,
  artifactType,
  onClose,
}: Props) {
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async () => {
    if (rating < 1) return;
    setBusy(true);
    try {
      await postArtifactRating(sessionId, {
        rating,
        artifact_id: artifactId,
        artifact_type: artifactType,
        comment: comment.trim() || undefined,
      });
      setDone(true);
      setTimeout(onClose, 800);
    } catch {
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-argus border border-argus-border-subtle bg-surface p-3">
      {done ? (
        <p className="text-sm text-emerald-700">Thanks for the feedback.</p>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-argus-primary">
              How was this {artifactType || "deliverable"}?
            </span>
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-argus-secondary hover:text-argus-primary"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
          <div className="mt-2 flex gap-1" role="radiogroup" aria-label="Rating">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                type="button"
                role="radio"
                aria-checked={rating === n}
                onMouseEnter={() => setHover(n)}
                onMouseLeave={() => setHover(0)}
                onClick={() => setRating(n)}
                className={`text-xl ${
                  (hover || rating) >= n ? "text-amber-500" : "text-argus-border-moderate"
                }`}
              >
                ★
              </button>
            ))}
          </div>
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Optional — e.g. structure was good but the 2x2 axes felt off"
            className="mt-2 w-full rounded border border-argus-border-subtle px-2 py-1 text-xs"
          />
          <Button className="mt-2" onClick={submit} disabled={busy || rating < 1}>
            {busy ? "Saving…" : "Submit rating"}
          </Button>
        </>
      )}
    </div>
  );
}
