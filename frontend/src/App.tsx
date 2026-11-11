// Quale pagina mostrare (todo 51). Legge `?period=` e `?view=` dall'URL e
// segue il tasto indietro del browser; la pagina sceglie da sola il resto
// dei suoi parametri (il giorno, il lunedi', i giorni del Trend).
import { useEffect, useState } from "react";

import { DayPage } from "./components/DayPage";
import { PlanPage } from "./components/PlanPage";
import { WeekPage } from "./components/WeekPage";
import { pageFromUrl, viewFromUrl, type Page, type View } from "./navigation";

// I due assi si leggono insieme, perche' le viste sono di ogni periodo
// (todo 59): quale sia quella giusta lo si sa solo dopo aver visto che
// pagina e'.
function here(): { page: Page; view: View } {
  const page = pageFromUrl();
  return { page, view: viewFromUrl(page) };
}

export function App() {
  const [{ page, view }, setHere] = useState(here);

  useEffect(() => {
    const onPop = () => setHere(here());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // La Plan di viste non ne ha: `view` si ignora.
  if (page === "week") return <WeekPage view={view} />;
  if (page === "plan") return <PlanPage />;
  return <DayPage view={view} />;
}
