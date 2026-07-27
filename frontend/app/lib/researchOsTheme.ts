// Dark-card "Research OS" prototype look, scoped to research OS pages.
// The rest of the app keeps the shared white-card T tokens.
// To revert a page to white-card consistency: swap card/well/line to light
// values and set ink -> T.text, keeping only the accent + serif changes.
export const M = {
  canvas: '#06192D',
  canvas2: '#081D33',
  sidebar: '#06172A',
  card: '#0C213A',
  cardElev: '#112A48',
  well: '#08182D',
  line: '#213A59',
  line2: '#2B496B',
  ink: '#E9F0FA',
  inkDim: '#93A6C5',
  inkFaint: '#607394',
  accent: '#2F7DFF',
  accentSoft: 'rgba(47, 125, 255, 0.14)',
  accentBright: '#63A3FF',
  pos: '#66D995',
  neg: '#F16D64',
  warn: '#E8BA4D',
  canvasInk: '#E9F0FA',
  canvasInkDim: '#A8B9D5',
  canvasInkFaint: '#7184A7',
  dangerWell: 'rgba(122, 42, 55, 0.36)',
  shadow: '0 22px 60px rgba(0, 0, 0, 0.22)',
  serif: "'Newsreader', Georgia, serif",
  sans: "Inter, ui-sans-serif, system-ui, sans-serif",
  mono: "'IBM Plex Mono', ui-monospace, monospace",
} as const;
