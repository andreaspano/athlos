#!/usr/bin/env python3
"""Le cinque icone della scala: Terrible, Low, Medium, High, Perfect.

Si rilancia per rifarle (`python3 tools/scale_icons.py`): i file in `icons/`
sono il prodotto, questo e' il disegno. Cambiare un colore o la piega di una
bocca si fa qui, non in un editor di immagini, cosi' le cinque restano
cinque varianti di una cosa sola.

Stessa forma delle icone che ci sono gia' (512x512, cerchio pieno a tinta
unita e glifo bianco piatto, un margine stretto attorno): cambia il colore e
cambia la bocca, e sono le due cose che dicono il valore. Niente sopracciglia
e niente gradienti — le altre icone non ne hanno, e cinque facce che cambiano
una cosa sola si leggono come una scala invece che come cinque disegni.

Disegnate a 4x e ridotte: PIL non ha l'antialiasing sui bordi, e un cerchio
di 2048 px ridotto a 512 con LANCZOS ha gli stessi bordi puliti degli altri
file.
"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "icons"
SIZE = 512
SCALE = 4
S = SIZE * SCALE

# Il colore porta il valore anche a icona piccola, dove la bocca e' tre
# pixel: dal rosso cupo al verde acqua, col celeste in mezzo. Tutti e cinque
# abbastanza scuri da reggere il glifo bianco, che e' la regola delle icone
# che ci sono (l'arancio della corsa, il carminio del recupero): il celeste
# e' il piu' chiaro dei cinque, come l'ambra che stava al suo posto.
FACES = [
    ("terrible", (176, 35, 47), -0.20),
    ("low",      (224, 122, 47), -0.09),
    ("medium",   (84, 169, 212), 0.0),
    ("high",     (76, 154, 82), 0.11),
    ("perfect",  (31, 138, 112), 0.22),
]


def bezier(p0, p1, p2, steps=600):
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        yield (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
               u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])


def stamp(draw, points, radius, fill):
    """La linea come una fila di cerchi: da' i capi tondi che `draw.line` non
    ha, e una curva senza spigoli."""
    for x, y in points:
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=fill)


def face(color, curve):
    """Una faccia. `curve` e' quanto la bocca si piega: negativo in giu'
    (∩, scontenta), zero dritta, positivo in su' (∪, contenta)."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 0.035 * S
    d.ellipse([m, m, S - m, S - m], fill=color + (255,))

    white = (255, 255, 255, 255)
    eye_r = 0.052 * S
    for ex in (0.355, 0.645):
        d.ellipse([ex * S - eye_r, 0.40 * S - eye_r, ex * S + eye_r, 0.40 * S + eye_r], fill=white)

    # La bocca: gli angoli fermi, il centro che sale o scende. Cosi' la
    # larghezza non cambia da un'icona all'altra e le cinque si confrontano.
    x0, x1 = 0.315 * S, 0.685 * S
    y_corner = (0.635 - curve * 0.42) * S
    y_mid = (0.635 + curve * 1.25) * S
    stamp(d, bezier((x0, y_corner), (0.5 * S, y_mid), (x1, y_corner)), 0.047 * S, white)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


for name, color, curve in FACES:
    path = OUT / f"{name}.png"
    face(color, curve).save(path)
    print(f"{path.name}: {path.stat().st_size} byte")
