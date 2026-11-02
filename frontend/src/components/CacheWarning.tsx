// La cache delle attivita' non in pari (todo 93).
//
// Dal todo 93 una ricostruzione non parte piu' da sola: dura mezz'ora, e
// partiva dentro la richiesta di chi apriva una pagina. Quando il codice
// vuole una versione diversa da quella in tabella, l'API serve le righe che
// ci sono — vere, calcolate col codice di prima — e dice perche'.
//
// **Dirlo e' la meta' del lavoro**: dati vecchi serviti in silenzio sono la
// stessa bugia che il banner dello scaricamento mancato esiste per non
// raccontare. Lo stesso aspetto, per lo stesso motivo.
//
// Non e' legato al tasto Refresh: non aspetta di aver visto un lavoro
// (`watched`) e non guarda di che tipo e', perche' la cache e' una sola per
// tutte e due le pagine.
export function CacheWarning({
  state,
}: {
  state: { ok: boolean; message: string | null } | null | undefined;
}) {
  if (!state || state.ok) return null;
  return (
    <p className="warning multiline">
      The activity cache is not current: {state.message}
    </p>
  );
}
