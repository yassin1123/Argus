import { sanitizeUserFacingText } from "@/lib/formatters";
import type { ConsultingPayload } from "@/lib/types";

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
      {children}
    </p>
  );
}

export function ConsultingFrame({ cp }: { cp: ConsultingPayload }) {
  const dc = cp.decision_criteria ?? [];
  const om = cp.options_matrix ?? [];
  const kill = cp.kill_criteria ?? [];
  const ei = cp.executive_insights ?? [];
  const krs = cp.key_risks_structured ?? [];

  const has =
    dc.length > 0 ||
    om.length > 0 ||
    kill.length > 0 ||
    ei.length > 0 ||
    krs.length > 0 ||
    cp.what_would_change_our_mind ||
    cp.evidence_ledger_summary;

  if (!has) return null;

  return (
    <section className="mb-10 rounded-[20px] border border-argus-border-subtle bg-surface p-6 shadow-argus-sm md:p-8">
      <SectionLabel>Consulting deliverable</SectionLabel>

      {ei.length > 0 && (
        <div className="mb-8">
          <h3 className="text-lg font-semibold text-argus-primary">Executive insights</h3>
          <ul className="mt-3 space-y-2">
            {ei.map((row, i) => (
              <li key={i} className="text-sm leading-relaxed text-argus-secondary">
                {sanitizeUserFacingText(String(row.text ?? ""))}
              </li>
            ))}
          </ul>
        </div>
      )}

      {krs.length > 0 && (
        <div className="mb-8">
          <h3 className="text-lg font-semibold text-argus-primary">Key risks</h3>
          <ul className="mt-3 space-y-2">
            {krs.map((row, i) => (
              <li key={i} className="text-sm leading-relaxed text-argus-secondary">
                {sanitizeUserFacingText(String(row.text ?? ""))}
              </li>
            ))}
          </ul>
        </div>
      )}

      {dc.length > 0 && (
        <div className="mb-8">
          <h3 className="text-lg font-semibold text-argus-primary">Decision criteria</h3>
          <ul className="mt-4 space-y-4">
            {dc.map((row, i) => {
              const r = row as Record<string, unknown>;
              return (
                <li
                  key={i}
                  className="rounded-[14px] border border-argus-border-subtle bg-canvas/50 px-4 py-3 text-sm"
                >
                  <span className="font-semibold text-argus-primary">
                    {String(r.criterion ?? "")}
                  </span>
                  <span className="ml-2 text-argus-tertiary">· {String(r.weight ?? "")}</span>
                  <p className="mt-1 text-argus-secondary">{String(r.how_met ?? "")}</p>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {om.length > 0 && (
        <div className="mb-8 overflow-x-auto">
          <h3 className="text-lg font-semibold text-argus-primary">Options comparison</h3>
          <table className="mt-4 w-full min-w-[480px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-argus-border-subtle text-left">
                <th className="py-2 pr-4 font-semibold text-argus-tertiary">Dimension</th>
                {om.map((row, i) => (
                  <th key={i} className="py-2 px-3 font-semibold text-argus-primary">
                    {String((row as Record<string, unknown>).option ?? `Option ${i + 1}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="text-argus-secondary">
              <tr className="border-b border-argus-border-subtle align-top">
                <td className="py-3 pr-4 font-medium text-argus-tertiary">Fit</td>
                {om.map((row, i) => (
                  <td key={i} className="py-3 px-3">
                    {String((row as Record<string, unknown>).fit ?? "—")}
                  </td>
                ))}
              </tr>
              <tr className="border-b border-argus-border-subtle align-top">
                <td className="py-3 pr-4 font-medium text-argus-success">Pros</td>
                {om.map((row, i) => {
                  const pros = Array.isArray((row as Record<string, unknown>).pros)
                    ? ((row as Record<string, unknown>).pros as string[])
                    : [];
                  return (
                    <td key={i} className="py-3 px-3">
                      <ul className="list-inside list-disc space-y-1">
                        {pros.length ? pros.map((p, j) => <li key={j}>{p}</li>) : <li>—</li>}
                      </ul>
                    </td>
                  );
                })}
              </tr>
              <tr className="align-top">
                <td className="py-3 pr-4 font-medium text-argus-warning">Cons</td>
                {om.map((row, i) => {
                  const cons = Array.isArray((row as Record<string, unknown>).cons)
                    ? ((row as Record<string, unknown>).cons as string[])
                    : [];
                  return (
                    <td key={i} className="py-3 px-3">
                      <ul className="list-inside list-disc space-y-1">
                        {cons.length ? cons.map((c, j) => <li key={j}>{c}</li>) : <li>—</li>}
                      </ul>
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {kill.length > 0 && (
        <div className="mb-8">
          <h3 className="text-lg font-semibold text-argus-primary">Kill criteria</h3>
          <ul className="mt-3 space-y-2">
            {kill.map((k, i) => (
              <li key={i} className="text-sm text-argus-secondary">
                {k}
              </li>
            ))}
          </ul>
        </div>
      )}

      {cp.evidence_ledger_summary ? (
        <div>
          <h3 className="text-sm font-semibold text-argus-primary">Evidence ledger</h3>
          <p className="mt-2 text-sm leading-relaxed text-argus-secondary">
            {cp.evidence_ledger_summary}
          </p>
        </div>
      ) : null}
    </section>
  );
}
