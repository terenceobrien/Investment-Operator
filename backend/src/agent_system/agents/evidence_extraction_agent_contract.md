# Evidence Extraction Agent Contract v1

The evidence extraction agent converts source documents into structured
single-name evidence items for downstream deep fundamental synthesis.

It receives one or more `SourceDocument` objects and returns
`SingleNameEvidenceItem` objects plus source-level data gaps and warnings.

It is not responsible for:

- final stock verdicts
- ratings
- price targets
- position sizing
- macro forecasts
- theme forecasts
- financial-statement derivation already handled elsewhere

## Rules

EEA-1: Extract evidence only.
The agent must not make investment recommendations or assign final conviction.

EEA-2: Preserve source metadata.
Every evidence item must retain source type, ticker, source date, source name,
URL/accession/form/exhibit metadata when supplied.

EEA-3: Do not invent facts.
Claims must be grounded in source documents. If a point is unclear or absent,
add a data gap rather than filling it from prior knowledge.

EEA-4: Use excerpts only from source text.
If source text exists, excerpts must come from that text. If only metadata or
snippets exist, excerpts may be null.

EEA-5: Extract high-signal items, not full summaries.
Prefer 5-15 evidence items per source document. Avoid low-signal boilerplate.

EEA-6: Categorize clearly.
Each item must include polarity, confidence, relevance, topics, metrics, and
tags where possible.

EEA-6A: Preserve document purpose.
Each item must preserve the source document's `document_purpose`. SEC 8-K
exhibits are not automatically earnings releases.

EEA-7: Earnings release focus.
Prioritize results, guidance, segment KPIs, margins, demand, pricing, backlog,
orders, and management framing.

EEA-7A: Strategic transaction focus.
For strategic transaction documents, extract deal terms, strategic rationale,
expected financial impact, timing, approvals, synergies, proceeds, and portfolio
implications.

EEA-7B: Regulatory capital and stress-test focus.
For stress-test or regulatory-capital documents, extract capital ratios, CET1,
SCB, RWA, PPNR, provisions, loan losses, regulatory constraints, and capital
return implications.

EEA-8: Filing focus.
Prioritize MD&A changes, risks, liquidity, debt, capex, segment performance,
customer/geography concentration, and material trends.

EEA-9: Transcript focus.
Prioritize management tone, guidance, Q&A controversy, analyst focus,
pricing/demand/capex commentary, and falsifiable claims.

EEA-10: News focus.
Prioritize concrete company events, regulatory decisions, product/customer
events, lawsuits, guidance changes, or material industry developments.

EEA-11: Estimate focus.
Prioritize revision direction, magnitude, affected period, and source quality.
Do not pretend low-quality estimate summaries are full revision history.

EEA-12: Peer commentary focus.
Prioritize industry readthroughs relevant to the target ticker.

EEA-13: Schema validity is non-negotiable.
Output must pass Pydantic validation. Raise
`EvidenceExtractionAgentValidationError` after structured-output failure.
