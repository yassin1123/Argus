import { Skeleton } from "@/components/ui/Skeleton";

export function EvidenceRailSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-4 w-24" />
      {[1, 2, 3, 4, 5].map((i) => (
        <Skeleton key={i} className="h-[70px] w-full" />
      ))}
    </div>
  );
}

export function AnswerColumnSkeleton() {
  return (
    <div className="space-y-6">
      <div className="relative overflow-hidden rounded-[20px] border border-argus-border-subtle bg-surface pl-1 pr-6 py-8">
        <Skeleton className="absolute left-0 top-0 h-full w-1 bg-argus-gold" />
        <Skeleton className="ml-4 h-6 w-32" />
        <Skeleton className="ml-4 mt-6 h-24 w-full" />
        <Skeleton className="ml-4 mt-4 h-16 w-full" />
      </div>
      <Skeleton className="h-3 w-28" />
      {[1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-20 w-full rounded-[14px]" />
      ))}
    </div>
  );
}

export function TrustRailSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-24 w-full rounded-[14px]" />
      <Skeleton className="h-40 w-full rounded-[14px]" />
    </div>
  );
}
