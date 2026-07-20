// Dark-card "Research OS" prototype look, scoped to research OS pages.
// The rest of the app keeps the shared white-card T tokens.
// To revert a page to white-card consistency: swap card/well/line to light
// values and set ink -> T.text, keeping only the accent + serif changes.
export const M = {
  canvas: '#DBE4F1',
  card: '#212F4F',
  cardElev: '#293A5F',
  well: '#16213C',
  line: '#2E3F63',
  line2: '#3A4D76',
  ink: '#E8EDF7',
  inkDim: '#8B98B4',
  inkFaint: '#5B6A8C',
  accent: '#4B8DFF',
  accentSoft: '#1E2F54',
  accentBright: '#6AA3FF',
  pos: '#3FD08A',
  neg: '#F2765F',
  warn: '#E8B74A',
  canvasInk: '#1A2540',
  canvasInkDim: '#4A5A7A',
  canvasInkFaint: '#6B7A99',
  serif: "'Newsreader', Georgia, serif",
  sans: "Inter, ui-sans-serif, system-ui, sans-serif",
  mono: "'IBM Plex Mono', ui-monospace, monospace",
} as const;
