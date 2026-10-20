#import "@preview/fletcher:0.5.8" as fletcher: diagram, edge, node

#set page(width: auto, height: auto, margin: 1em)
#set text(font: "New Computer Modern Sans", size: 10pt)

#let box = (stroke: 0.8pt, corner-radius: 3pt, inset: 8pt)
#let tbd = (stroke: (thickness: 0.8pt, dash: "dashed"), corner-radius: 3pt, inset: 8pt)
#let lbl(body) = text(size: 8pt, body)

// Edge with a label parallel to the arrow.
// side: which side of the line the label is on (left/right, seen from the start of the arrow)
// pos: position of the label along the line (0 = start, 1 = end)
#let rel(from, to, label, side: left, pos: 0.5) = edge(
  from,
  to,
  "->",
  lbl(label),
  label-angle: auto,
  label-side: side,
  label-pos: pos,
  label-sep: 3pt,
  mark-scale: 130%,
)

#diagram(
  spacing: (30mm, 22mm),
  node-stroke: 0.8pt,

  // Areas
  node(
    enclose: ((5.95, 2.4), (6.85, 3.7)),
    fill: green.lighten(70%),
    stroke: green.darken(20%),
    snap: false,
    inset: 8pt,
  ),
  node(enclose: ((0, -2.2), (4, 0.4)), fill: orange.lighten(85%), stroke: orange.darken(20%), snap: false, inset: 8pt),
  node(
    enclose: ((1.4, 1.4), (5.6, 6.1)),
    fill: fuchsia.lighten(85%),
    stroke: fuchsia.darken(20%),
    snap: false,
    inset: 8pt,
  ),
  node(enclose: ((7.3, 2.1), (10.4, 6.1)), fill: blue.lighten(90%), stroke: blue.darken(20%), snap: false, inset: 8pt),

  // Area titles
  node((6.4, 2.75), [*Database*], stroke: none),
  node((2, -1.85), [*Frontend*], stroke: none),
  node((4.25, 1.7), [*Backend*], stroke: none),
  node((8.9, 2.4), [*AI Server*], stroke: none),

  // Database
  node((6.4, 3.2), [Postgres], name: <pg>, fill: white, ..box),

  // Frontend
  node((2, -1.2), [SvelteKit], name: <svelte>, fill: white, ..box),
  node((0.5, 0), [User client], name: <user>, fill: white, ..box),
  node((2, 0), [QR code], name: <qr>, fill: white, ..box),
  node((3.5, 0), [Player client], name: <player>, fill: white, ..box),

  // Backend
  node((2, 2), [Rooms], name: <rooms>, fill: white, ..box),
  node((3.5, 2), [REST API], name: <rest>, fill: white, ..box),
  node((2.75, 3.2), [Server (FastAPI)], name: <server>, fill: white, ..box),
  node((2.75, 4.6), [Song cache], name: <cache>, fill: white, ..box),
  node((4.4, 4.6), [yt-dlp], name: <ytdlp>, fill: white, ..box),
  node((2, 5.7), [Queue management], name: <queue>, fill: white, ..box),

  // AI Server
  node((8.9, 3.0), [llama.cpp], name: <llama>, fill: white, ..box),
  node((8.1, 4.3), [Audio decision model \ (TBD)], name: <audio>, fill: white, ..tbd),
  node((9.7, 4.3), [Text decision model \ (TBD)], name: <text>, fill: white, ..tbd),
  node((8.9, 5.7), [Systemone API], name: <sys>, fill: white, ..box),

  // Frontend relations
  rel(<svelte>, <user>, [renders], side: right),
  rel(<svelte>, <player>, [renders], side: left),
  rel(<user>, <qr>, [scans], side: left),
  rel(<player>, <qr>, [displays], side: right),
  rel(<user>, <rest>, [shares songs via], side: right, pos: 0.33),
  rel(<player>, <rest>, [manages queue via], side: left),
  rel(<qr>, <rooms>, [links to], side: right, pos: 0.75),

  // Backend relations
  rel(<server>, <rooms>, [manages], side: left),
  rel(<server>, <rest>, [exposes], side: left),
  rel(<server>, <pg>, [stores data in], side: left),
  rel(<server>, <cache>, [reads songs from], side: left),
  rel(<cache>, <ytdlp>, [downloads with], side: left),
  rel(<rooms>, <queue>, [uses], side: right),
  rel(<cache>, <queue>, [supplies songs to], side: left),
  rel(<queue>, <sys>, [requests decisions from], side: left, pos: 0.35),

  // AI Server relations
  rel(<llama>, <audio>, [runs], side: right),
  rel(<llama>, <text>, [runs], side: left),
  rel(<audio>, <sys>, [sends results to], side: right),
  rel(<text>, <sys>, [sends results to], side: left),
)
