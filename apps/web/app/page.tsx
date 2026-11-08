import { SystemStatus } from "@/components/system-status";
import { config } from "@/lib/config";

export default function Home() {
  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{config.productName}</h1>
      <p className="mt-2 text-muted-foreground">Foundation is running. Service status:</p>
      <div className="mt-8">
        <SystemStatus />
      </div>
    </main>
  );
}
