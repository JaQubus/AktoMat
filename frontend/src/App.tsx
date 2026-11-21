import { useEffect, useState } from "react";

// M1: frontend pracuje na mocku Karty (GET /api/mock/karta). Pełny widok w M8.
type Pole = { value: unknown; status: string; source?: string };

export default function App() {
  const [karta, setKarta] = useState<any>(null);
  useEffect(() => { fetch("/api/mock/karta").then((r) => r.json()).then(setKarta).catch(() => setKarta(null)); }, []);
  const nazwa: Pole | undefined = karta?.odwolujacy?.nazwa;
  return (
    <div className="min-h-screen bg-white text-slate-900 dark:bg-slate-900 dark:text-slate-100 p-6">
      <header className="mb-4 flex items-center gap-3">
        <h1 className="text-xl font-semibold">ODWOŁANIA2JSON</h1>
        <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">DANE FIKCYJNE / MOCK</span>
      </header>
      <p>{nazwa ? `Odwołujący: ${String(nazwa.value)} (${nazwa.status})` : "Ładowanie mocka Karty…"}</p>
    </div>
  );
}
