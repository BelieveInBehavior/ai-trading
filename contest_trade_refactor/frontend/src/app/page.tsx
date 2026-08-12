import TradingDashboard from "@/components/TradingDashboard";
import type { HealthStatus, SystemStatus } from "@/types/trading";

async function fetchServerData(): Promise<{
  health: HealthStatus | null;
  status: SystemStatus | null;
}> {
  try {
    const [healthRes, statusRes] = await Promise.all([
      fetch("http://localhost:8000/api/health", {
        cache: "no-store",
        next: { revalidate: 0 },
      }),
      fetch("http://localhost:8000/api/status", {
        cache: "no-store",
        next: { revalidate: 0 },
      }),
    ]);
    const health: HealthStatus = await healthRes.json();
    const status: SystemStatus = await statusRes.json();
    return { health, status };
  } catch {
    // Backend may not be running during build — degrade gracefully
    return { health: null, status: null };
  }
}

export default async function HomePage() {
  const { health, status } = await fetchServerData();
  return <TradingDashboard initialHealth={health} initialStatus={status} />;
}
