# Company Profile Agent Contract v1

The company profile agent generates structured business profiles for public
companies so downstream fundamental, theme-mapping, and research agents can
understand what the company does. It is a profile builder, not an investment
underwriter.

The agent receives:

- ticker
- company_name, sector, and industry if available
- financial_context if available
- research_context if available
- existing partial profile if available
- as_of_date

The agent answers:

- What does this company do?
- How does it make money?
- What are its main segments?
- What drives revenue, margins, and costs?
- Who are relevant peers?
- What macro and theme sensitivities matter?
- What company-specific risks matter?

It is not responsible for:

- final verdicts
- price targets
- trade recommendations
- position sizing
- underwriting scores
- current news synthesis unless supplied in context

## Rules

CPA-1: Output is a company profile, not an investment opinion.
The agent must not produce a final verdict, price target, trade recommendation,
position sizing, or underwriting score.

CPA-2: Use supplied context first.
If supplied company facts, financial context, research context, or metadata
exist, the agent must use them before relying on general prior knowledge.

CPA-3: Label unverified priors.
If the profile is generated from general model knowledge without source-backed
research context, set `profile_source = "llm_generated_unverified"` and include
source notes explaining that the profile should be verified with filings.

CPA-4: No invented specifics.
Do not invent exact segment percentages, revenue shares, customer
concentration, supplier relationships, current backlog, management commentary,
or recent news unless provided in source context.

CPA-5: Use nulls for unknowns.
If segment revenue/profit shares are unknown, set them to null. Do not guess
percentages.

CPA-6: Peers must be real and relevant.
Peer tickers should be real, tradeable, and relevant. Prefer US tickers or ADRs
where available. If uncertain, omit rather than hallucinate.

CPA-7: Segment logic must be economically useful.
Segments should reflect how the business is actually analyzed. For banks, use
banking units and KPIs; for hardware, product/services lines; for energy,
upstream/midstream/downstream; for REITs, property type and geography.

CPA-8: Macro sensitivities must be specific.
Avoid generic "economy" or "market conditions." Use specific sensitivities like
rates, credit cycle, consumer spending, FX, commodity prices, AI capex, cloud
capex, construction cycle, loan growth, deposit beta, or regulation.

CPA-9: Theme exposures must be mappable.
Thematic exposures should be concise phrases that `theme_mapping_agent` can map
to active macro themes.

CPA-10: Risks must be company-relevant.
Major risks should be specific to the business model, industry, balance sheet,
regulation, demand cycle, competition, and valuation sensitivity.

CPA-11: Sector-specific awareness.
For banks, insurers, REITs, energy, semiconductors, software, biotech, and
consumer names, the profile must use sector-appropriate drivers and KPIs.

CPA-12: Confidence reflects source quality.
If only ticker and financial metadata are provided, `profile_confidence` should
usually be medium at best. If research_context includes recent filing or
transcript evidence, confidence can be high. If the ticker is obscure or the
model is uncertain, confidence should be low.

CPA-13: Schema validity is non-negotiable.
Output must pass full Pydantic validation. Raise
`CompanyProfileAgentValidationError` after structured-output failure.

## Failure Modes

- inventing segment percentages
- hallucinating peers
- treating a business profile as a stock recommendation
- generic macro sensitivities
- generic risks
- profile confidence too high without sources
- failing to populate theme exposures
- failing to populate peer group for obvious large-cap names
- using irrelevant peers
- not distinguishing bank, REIT, insurance, energy, semiconductor, software,
  biotech, or consumer-specific business models
