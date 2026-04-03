import { HomeHeader } from "@/components/home/HomeHeader";
import { ComposerCard } from "@/components/home/ComposerCard";

export default function HomePage() {
  return (
    <main className="flex min-h-[calc(100vh-3.5rem)] flex-col">
      <div className="flex flex-1 flex-col items-center justify-center px-4 py-16 md:py-24">
        <div className="w-full max-w-[660px]">
          <HomeHeader />
          <ComposerCard />
        </div>
      </div>
    </main>
  );
}
