#import "@preview/fletcher:0.5.8" as fletcher: diagram, edge, node

#set page(width: auto, height: auto, margin: 1em)
#set text(font: "New Computer Modern Sans", size: 10pt)

#let box = (stroke: 0.8pt, corner-radius: 3pt, inset: 8pt)
#let tbd = (stroke: (thickness: 0.8pt, dash: "dashed"), corner-radius: 3pt, inset: 8pt)
#let lbl(body) = text(size: 8pt, body)

// Edge with a label parallel to the arrow.
// side: which side of the line the label is on (left/right, seen from the start of the arrow)
// pos: position of the label along the line (0 = start, 1 = end)
#let rel(from, to, label, side: left, pos: 0.5, dash: none) = edge(
  from,
  to,
  "->",
  lbl(label),
  label-angle: auto,
  label-side: side,
  label-pos: pos,
  label-sep: 3pt,
  mark-scale: 130%,
  ..if dash != none { (stroke: (dash: dash)) },
)

#diagram(
  spacing: (30mm, 22mm),
  node-stroke: 0.8pt,

  // Areas
  node(enclose: ((0, -2.2), (4, 0.4)), fill: orange.lighten(85%), stroke: orange.darken(20%), snap: false, inset: 8pt),
  node(
    enclose: ((-0.5, 2.1), (5.4, 5.6)),
    fill: fuchsia.lighten(85%),
    stroke: fuchsia.darken(20%),
    snap: false,
    inset: 8pt,
  ),
  node(
    enclose: ((-0.5, 6.4), (5.4, 7.6)),
    fill: green.lighten(70%),
    stroke: green.darken(20%),
    snap: false,
    inset: 8pt,
  ),
  node(enclose: ((6.2, 2.1), (9.2, 5.6)), fill: blue.lighten(90%), stroke: blue.darken(20%), snap: false, inset: 8pt),

  // Area titles
  node((2, -1.85), [*Frontend*], stroke: none),
  node((2.45, 2.4), [*Backend* (one FastAPI service per bounded context)], stroke: none),
  node((2.45, 6.75), [*Database* (Postgres, one database per service)], stroke: none),
  node((7.7, 2.4), [*AI Server*], stroke: none),

  // Frontend
  node((2, -1.2), [SvelteKit], name: <svelte>, fill: white, ..box),
  node((0.5, 0), [User client], name: <user>, fill: white, ..box),
  node((2, 0), [QR code], name: <qr>, fill: white, ..box),
  node((3.5, 0), [Player client], name: <player>, fill: white, ..box),

  // Gateway
  node((2, 1.2), [API gateway (Caddy)], name: <gw>, fill: white, ..box),

  // Backend services
  node((0.2, 3.5), [*Auth* \ users, JWT], name: <auth>, fill: white, ..box),
  node((2.45, 3.5), [*Queues* \ rooms, queue, votes], name: <queues>, fill: white, ..box),
  node((4.7, 3.5), [*Songs* \ song cache], name: <songs>, fill: white, ..box),
  node((4.7, 4.7), [yt-dlp], name: <ytdlp>, fill: white, ..box),
  node((2.45, 5.0), [*Common* library \ JWT check, HTTP client], name: <common>, fill: white, ..tbd),

  // Databases
  node((0.2, 7.1), [Auth DB], name: <authdb>, fill: white, ..box),
  node((2.45, 7.1), [Queues DB], name: <queuesdb>, fill: white, ..box),
  node((4.7, 7.1), [Songs DB], name: <songsdb>, fill: white, ..box),

  // AI Server
  node((7.7, 3.2), [*Tagger* \ (inference)], name: <tagger>, fill: white, ..box),
  node((7.7, 4.4), [*Decision* \ llama.cpp], name: <llama>, fill: white, ..tbd),
  node((7.7, 5.2), [Audio and text models \ (TBD)], name: <models>, fill: white, ..tbd),

  // Frontend relations
  rel(<svelte>, <user>, [renders], side: right),
  rel(<svelte>, <player>, [renders], side: left),
  rel(<user>, <qr>, [scans], side: left),
  rel(<player>, <qr>, [displays], side: right),
  rel(<user>, <gw>, [shares songs via], side: right, pos: 0.4),
  rel(<player>, <gw>, [manages queue via], side: left, pos: 0.4),

  // Gateway relations (the UI talks only to the gateway)
  rel(<gw>, <auth>, [/api/auth], side: right),
  rel(<gw>, <queues>, [/api/room], side: right),
  rel(<gw>, <songs>, [/api/song], side: right),

  // Service to service relations (HTTP, never through the gateway)
  rel(<queues>, <songs>, [requests and reads songs], side: left),
  rel(<queues>, <auth>, [reads user names], side: right),
  rel(<auth>, <queues>, [deletes user data], side: right, pos: 0.5),
  rel(<songs>, <ytdlp>, [downloads with], side: left),
  rel(<songs>, <tagger>, [tags songs with], side: left),
  rel(<queues>, <llama>, [asks decisions (later)], side: right, pos: 0.65, dash: "dashed"),
  rel(<llama>, <models>, [runs], side: left),

  // Library
  edge(<common>, <auth>, "->", lbl[used by], label-side: left, label-angle: auto, stroke: (dash: "dotted")),
  edge(<common>, <queues>, "->", stroke: (dash: "dotted")),
  edge(<common>, <songs>, "->", stroke: (dash: "dotted")),

  // Data relations
  rel(<auth>, <authdb>, [owns], side: right),
  rel(<queues>, <queuesdb>, [owns], side: right, pos: 0.85),
  rel(<songs>, <songsdb>, [owns], side: right),
)
