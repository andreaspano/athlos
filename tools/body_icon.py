#!/usr/bin/env python3
"""L'icona della card Body: il corpo che sale sulla bilancia.

Si rilancia per rifarla (`python3 tools/body_icon.py`): il file in `icons/`
e' il prodotto, questo e' il disegno. Vale la stessa regola delle cinque
facce (`tools/scale_icons.py`) — un colore o una curva si cambiano qui, non
in un editor di immagini.

Stessa forma delle icone che ci sono (512x512, cerchio pieno a tinta unita,
glifo bianco, margine stretto attorno) e **stesso modo di disegnare il
glifo** di Health e Recovery: un contorno bianco con la tinta che si vede
dentro, non una sagoma piena. Il ciano scuro e' il suo, perche' ogni card ha
il suo colore e quelli presi sono il viola della salute (#6252c4), il blu
della forma (#2563c8), il cremisi del recupero (#c2255c) e l'arancio di Next
(#e89614).

Il glifo e' una **persona**, testa e spalle, non una bilancia: a 22 px —
quanto e' grande davvero nell'intestazione della card — una bilancia e' un
quadrato con dentro qualcosa che non si distingue, e la card parla del corpo,
non dell'attrezzo che lo misura. Le spalle escono dal cerchio invece di
fermarsi dentro: tagliate dal bordo si leggono come spalle, chiuse in mezzo
come un ponte.

Disegnata a 4x e ridotta, come le facce: PIL non ha l'antialiasing sui bordi,
e un cerchio di 2048 px ridotto a 512 con LANCZOS ha gli stessi bordi puliti
degli altri file.
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "icons"
SIZE = 512
SCALE = 4
S = SIZE * SCALE

COLOR = (11, 114, 133, 255)  # ciano scuro
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)

MARGIN = 0.035  # lo stesso delle altre icone
STROKE = 0.058  # 30 px su 512, il tratto del glifo


def box(cx, cy, rx, ry=None):
    """Il rettangolo che PIL vuole per un'ellisse, da centro e raggi."""
    ry = rx if ry is None else ry
    return [(cx - rx) * S, (cy - ry) * S, (cx + rx) * S, (cy + ry) * S]


def icon():
    disc = Image.new("RGBA", (S, S), CLEAR)
    ImageDraw.Draw(disc).ellipse(box(0.5, 0.5, 0.5 - MARGIN), fill=COLOR)

    # Il glifo si disegna su un foglio suo e poi si taglia con il cerchio:
    # le spalle sono piu' larghe del disco, e senza il taglio il bianco
    # colerebbe fuori sul trasparente.
    glyph = Image.new("RGBA", (S, S), CLEAR)
    d = ImageDraw.Draw(glyph)
    # La testa: un anello, cioe' un cerchio bianco svuotato.
    d.ellipse(box(0.5, 0.355, 0.140), fill=WHITE)
    d.ellipse(box(0.5, 0.355, 0.140 - STROKE), fill=CLEAR)
    # Le spalle: la meta' di sopra di un anello ovale. Si disegna intero e si
    # cancella da meta' in giu', cosi' i due capi restano dritti e il bordo
    # del cerchio li taglia.
    d.ellipse(box(0.5, 0.900, 0.345, 0.330), fill=WHITE)
    d.ellipse(box(0.5, 0.900, 0.345 - STROKE, 0.330 - STROKE), fill=CLEAR)
    d.rectangle([0, 0.900 * S, S, S], fill=CLEAR)
    glyph.putalpha(ImageChops.multiply(glyph.getchannel("A"), disc.getchannel("A")))

    disc.alpha_composite(glyph)
    return disc.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == "__main__":
    path = OUT / "body.png"
    icon().save(path)
    print(f"{path.name}: {path.stat().st_size} byte")
