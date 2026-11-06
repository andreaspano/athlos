// Vite per la pagina Day in React (todo 33). In sviluppo `/api` e `/icons`
// passano all'API (`make api`, 127.0.0.1:8000): il frontend usa solo
// percorsi relativi, e cosi' non serve CORS.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const API = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  build: {
    // Vega (il grafico) da solo pesa piu' di un megabyte minificato: sta in
    // un pezzo a parte, caricato quando serve (`RunChart`), e il limite
    // dell'avviso si alza per lui.
    chunkSizeWarningLimit: 1500,
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    // Vite ascolta solo su 127.0.0.1, anche su mutolo.
    //
    // **Dal todo 82 la tailnet non passa piu' di qui.** Quello che gira
    // sulla macchina e' `athlos-api.service`, che serve l'API e la
    // pagina compilata sulla 8000, e `tailscale serve` punta li':
    //   sudo tailscale serve --bg --http=8000 http://127.0.0.1:8000
    // Questo file resta quello dello sviluppo: `make frontend` per avere il
    // ricaricamento a caldo, con l'API presa dal servizio sulla 8000. Per
    // vedere dalla tailnet il server di sviluppo invece della pagina
    // compilata:
    //   sudo tailscale serve --bg --http=5173 http://127.0.0.1:5173
    // L'host che arriva e' allora `mutolo` (MagicDNS, con la porta che Vite
    // non guarda), oppure `mutolo.<tailnet>.ts.net` se nella tailnet si
    // accendono i certificati HTTPS e si serve in https. Vite rifiuta i nomi
    // che non conosce, e li' servono entrambi.
    allowedHosts: [".ts.net", "mutolo"],
    proxy: {
      "/api": API,
      "/icons": API,
    },
  },
});
