// Il Markdown dei report in elementi React, e le sezioni del report
// giornaliero divise per riquadro (todo 34).
//
// I report usano solo paragrafi, elenchi e grassetto/corsivo: bastano poche
// righe di conversione, senza una libreria in piu' e senza
// `dangerouslySetInnerHTML`.
//
// I **piani** di `plan/` usano anche titoli e tabelle — un piano e' quasi
// tutto tabelle, le settimane e i ritmi — e quelli si convertono qui per lo
// stesso motivo: una libreria di Markdown costa piu' di trenta righe.
import type { ReactNode } from "react";

import type { Report, Verdict } from "./api/client";

/** Grassetto (`**...**`), corsivo (`*...*` o `_..._`) e codice (`` `...` ``)
 * dentro una riga. Il resto resta testo. */
export function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /\*\*(.+?)\*\*|`([^`]+)`|\*([^*\s][^*]*?)\*|\b_([^_]+?)_\b/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const at = match.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const key = out.length;
    if (match[1] != null) out.push(<strong key={key}>{inline(match[1])}</strong>);
    else if (match[2] != null) out.push(<code key={key}>{match[2]}</code>);
    else out.push(<em key={key}>{inline(match[3] ?? match[4] ?? "")}</em>);
    last = at + match[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const BULLET = /^\s*[-*+]\s+/;
const NUMBERED = /^\s*\d+\.\s+/;
// Un titolo: da uno a quattro cancelletti e uno spazio.
const HEADING = /^(#{1,4})\s+(.*)$/;
// La riga che divide l'intestazione di una tabella dal corpo: solo stanghette,
// trattini, due punti e spazi, e almeno un trattino.
const TABLE_RULE = /^[\s|:-]+$/;

/** I blocchi del testo, separati da righe vuote. */
function blocks(body: string): string[] {
  return body.split(/\n\s*\n/).filter((b) => b.trim());
}

/** Le voci di un blocco elenco: una riga che non inizia con il segno
 * continua la voce prima. `null` se il blocco non e' un elenco. */
function listItems(block: string): { ordered: boolean; items: string[] } | null {
  const lines = block.split("\n");
  const marker = BULLET.test(lines[0]) ? BULLET : NUMBERED.test(lines[0]) ? NUMBERED : null;
  if (!marker) return null;
  const items: string[] = [];
  for (const line of lines) {
    if (marker.test(line)) items.push(line.replace(marker, ""));
    else items[items.length - 1] += ` ${line.trim()}`;
  }
  return { ordered: marker === NUMBERED, items };
}

/** Le celle di una riga di tabella: quello che sta fra le stanghette. Le due
 * ai bordi non contano, quindi `| a | b |` sono due celle e non quattro. */
function cells(line: string): string[] {
  const text = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return text.split("|").map((cell) => cell.trim());
}

/** Le righe di un blocco tabella: l'intestazione e il corpo. `null` se il
 * blocco non e' una tabella, cioe' se non ha la riga di trattini sotto la
 * prima. */
function tableRows(block: string): { head: string[]; rows: string[][] } | null {
  const lines = block.split("\n");
  if (lines.length < 2 || !lines[0].includes("|")) return null;
  if (!TABLE_RULE.test(lines[1]) || !lines[1].includes("-")) return null;
  return {
    head: cells(lines[0]),
    rows: lines.slice(2).filter((line) => line.includes("|")).map(cells),
  };
}

/** Una tabella. Scorre in orizzontale da sola dove non ci sta (il CSS di
 * `.prose table`): le tabelle dei piani hanno righe lunghe, e una pagina che
 * scorre di lato tutta intera e' peggio. */
function table(block: string, key: number): ReactNode | null {
  const parsed = tableRows(block);
  if (!parsed) return null;
  return (
    <div className="table-scroll" key={key}>
      <table>
        <thead>
          <tr>
            {parsed.head.map((cell, i) => (
              <th key={i}>{inline(cell)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {parsed.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>{inline(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** I pezzi del testo, uno per elemento da disegnare: i blocchi fra righe
 * vuote, con ogni **titolo staccato** dal resto del suo blocco. Dopo un `##`
 * ci vorrebbe una riga vuota, ma da un file scritto a mano non si pretende, e
 * il paragrafo attaccato al titolo non deve finire dentro di lui. */
function units(body: string): string[] {
  const out: string[] = [];
  for (const block of blocks(body)) {
    let buffer: string[] = [];
    const flush = () => {
      const text = buffer.join("\n").trim();
      if (text) out.push(text);
      buffer = [];
    };
    for (const line of block.split("\n")) {
      if (HEADING.test(line)) {
        flush();
        out.push(line);
      } else buffer.push(line);
    }
    flush();
  }
  return out;
}

/** Il testo come paragrafi, elenchi, titoli e tabelle. */
export function markdown(body: string): ReactNode[] {
  return units(body).map((block, key) => {
    // I titoli partono da `h2`: il titolo grande della pagina e' l'`h1`, e
    // dentro un riquadro non ce ne va un altro.
    const heading = block.match(HEADING);
    if (heading) {
      const level = Math.min(4, Math.max(2, heading[1].length));
      const Tag = `h${level}` as "h2" | "h3" | "h4";
      return <Tag key={key}>{inline(heading[2])}</Tag>;
    }
    const grid = table(block, key);
    if (grid) return grid;
    const list = listItems(block);
    if (!list) return <p key={key}>{inline(block.split("\n").join(" "))}</p>;
    const children = list.items.map((item, j) => <li key={j}>{inline(item)}</li>);
    return list.ordered ? <ol key={key}>{children}</ol> : <ul key={key}>{children}</ul>;
  });
}

/** Il corpo della sezione `title` del report, o `null`. */
export function sectionBody(report: Report | null, title: string): string | null {
  return report?.sections.find((s) => s.title?.toLowerCase() === title.toLowerCase())?.body ?? null;
}

/** Il voto che l'agente ha dato alla sua sezione (todo 92), o `null`.
 *
 * Lo scrive la sola Training, in una riga `verdict:` in cima al frammento
 * che l'API toglie dal testo: le altre card la faccia la prendono dai numeri
 * (`scores`). `null` anche su tutti i report scritti prima di quel todo. */
export function sectionVerdict(report: Report | null, title: string): Verdict | null {
  return (
    report?.sections.find((s) => s.title?.toLowerCase() === title.toLowerCase())?.verdict ?? null
  );
}

/** Il testo prima della prima sezione ("Data: local cache, ..."). */
export function preamble(report: Report | null): string | null {
  return report?.sections.find((s) => s.title == null)?.body ?? null;
}

/** L'icona della sezione `title` del report (il nome lo da' l'API), o
 * `null`. */
export function sectionIcon(report: Report | null, title: string): string | null {
  return report?.sections.find((s) => s.title?.toLowerCase() === title.toLowerCase())?.icon ?? null;
}

/** Quando e' stato scritto il testo della sezione `title`, o `null`. Le
 * sezioni di uno stesso giorno possono portare ore diverse: dal todo 47 il
 * giro della mattina ne scrive alcune e quello della sera altre. */
export function sectionWrittenAt(report: Report | null, title: string): string | null {
  return (
    report?.sections.find((s) => s.title?.toLowerCase() === title.toLowerCase())?.written_at ?? null
  );
}
