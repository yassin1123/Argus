import NotificationFeed from "@/components/Notifications/NotificationFeed";

export default function NotificationsPage() {
  return (
    <main className="mx-auto max-w-[700px] px-8 py-12">
      <h1 className="font-serif text-[28px] font-semibold text-argus-primary">
        Notifications
      </h1>
      <p className="mt-1 text-[13px] text-argus-tertiary">
        Mentions, review actions, section assignments, and tasks across every
        engagement you're on. Click a row to jump to the source.
      </p>
      <div className="mt-6">
        <NotificationFeed />
      </div>
    </main>
  );
}
