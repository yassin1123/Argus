import { Badge } from "@/components/ui/Badge";

export function SessionStatusPill({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "complete")
    return <Badge variant="success">Complete</Badge>;
  if (s === "processing" || s === "pending")
    return <Badge variant="info">Processing</Badge>;
  if (s === "failed") return <Badge variant="danger">Failed</Badge>;
  if (s === "insufficient") return <Badge variant="warning">Insufficient</Badge>;
  if (s === "draft") return <Badge variant="neutral">Draft</Badge>;
  return <Badge variant="neutral">{status}</Badge>;
}
