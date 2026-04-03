"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";

const PLACEHOLDER =
  "Should we expand into Germany or France first, and what would make us change that decision?";

export function AutoGrowTextarea({
  value,
  onChange,
  id,
  onFocus,
  onBlur,
}: {
  value: string;
  onChange: (v: string) => void;
  id?: string;
  onFocus?: () => void;
  onBlur?: () => void;
}) {
  const mirrorRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const [height, setHeight] = useState(180);

  const sync = useCallback(() => {
    const el = mirrorRef.current;
    if (!el) return;
    const h = Math.min(Math.max(el.scrollHeight, 180), 360);
    setHeight(h);
  }, []);

  useLayoutEffect(() => {
    sync();
  }, [value, sync]);

  return (
    <div className="relative">
      <div
        ref={mirrorRef}
        aria-hidden
        className="invisible min-h-[180px] max-h-[360px] whitespace-pre-wrap break-words px-0 pb-4 text-base leading-[1.7]"
      >
        {value || PLACEHOLDER}
        {"\u00a0"}
      </div>
      <textarea
        ref={taRef}
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={onFocus}
        onBlur={onBlur}
        placeholder={PLACEHOLDER}
        rows={1}
        style={{ height }}
        className="absolute inset-0 w-full resize-none overflow-y-auto bg-transparent text-base leading-[1.7] text-argus-primary placeholder:text-[#C4CBDA] focus:outline-none"
      />
    </div>
  );
}
