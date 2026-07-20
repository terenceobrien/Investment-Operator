"""Read-only query layer over daily NarrativeStateV1 snapshots."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.narrative.schema import DominantNarrative, InefficiencyMapItem, NarrativeStateV1
from src.narrative.synth import (
    load_latest_narrative_snapshot,
    narrative_snapshot_path,
)
from src.narrative.ticker_profiles import (
    get_ticker_profile,
    normalize_ticker,
    profile_terms,
)


SNAPSHOT_DIR = Path("data/snapshots")
LOOKBACK_DAYS = 7
DEFAULT_ARCHETYPE_ID = "narrative_fundamental_divergence"

CoverageQuality = Literal["high", "medium", "low", "absent", "stale"]
NarrativeStance = Literal["risk_on", "risk_off", "mixed", "unclear"]
PriceConfirmation = Literal["confirming", "contradicting", "partial", "unavailable"]
SectorAlignment = Literal["aligned", "diverging", "idiosyncratic", "no_sector_signal"]


class TickerNarrative(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    coverage_quality: CoverageQuality

    dominant_narrative_title: Optional[str] = None
    dominant_narrative_summary: Optional[str] = None
    stance: Optional[NarrativeStance] = None
    confidence: Optional[int] = None

    inefficiency_archetype_id: Optional[str] = None
    inefficiency_archetype_name: Optional[str] = None
    underlying_gap_type: Optional[str] = None

    price_confirmation: Optional[PriceConfirmation] = None

    sector_etf: Optional[str] = None
    sector_narrative_alignment: Optional[SectorAlignment] = None

    snapshot_date: str
    snapshot_subject: Optional[str] = None
    is_stale: bool = False
    source_narrative_indices: list[int] = Field(default_factory=list)


class SectorNarrative(BaseModel):
    model_config = ConfigDict(frozen=True)

    sector_etf: str
    coverage_quality: CoverageQuality

    dominant_narrative_title: Optional[str] = None
    dominant_narrative_summary: Optional[str] = None
    stance: Optional[NarrativeStance] = None
    confidence: Optional[int] = None

    sector_ticker_count: int = 0
    sector_tickers_in_narrative: list[str] = Field(default_factory=list)

    inefficiency_archetype_id: Optional[str] = None

    snapshot_date: str
    snapshot_subject: Optional[str] = None
    is_stale: bool = False


class DivergenceSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    sector_etf: str

    divergence_type: Literal[
        "stance_opposite",
        "archetype_mismatch",
        "idiosyncratic_story",
    ]

    ticker_stance: Optional[str] = None
    sector_stance: Optional[str] = None
    ticker_archetype: Optional[str] = None
    sector_archetype: Optional[str] = None
    rationale: str

    snapshot_date: str
    is_stale: bool = False


@dataclass(frozen=True)
class _LoadedSnapshot:
    state: NarrativeStateV1
    snapshot_date: str
    snapshot_subject: str
    stale_days: int

    @property
    def is_stale(self) -> bool:
        return self.stale_days > 0


@dataclass(frozen=True)
class _NarrativeCandidate:
    loaded: _LoadedSnapshot
    narrative: DominantNarrative
    index: int
    evidence_match: bool
    inefficiency: InefficiencyMapItem | None

    @property
    def confidence(self) -> int:
        return int(self.narrative.confidence or 0)

    @property
    def has_specific_archetype(self) -> bool:
        archetype = self.inefficiency.archetype_id if self.inefficiency else None
        return bool(archetype and not _is_default_archetype(archetype))


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _parse_snapshot_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _load_snapshot_for_subject(subject_key: str) -> _LoadedSnapshot | None:
    subject = normalize_ticker(subject_key)
    today = _today_utc()
    today_str = today.isoformat()

    today_path = narrative_snapshot_path(SNAPSHOT_DIR, today_str, subject_key=subject)
    raw: dict | None = None
    snapshot_date = today_str
    if today_path.exists():
        try:
            raw = json.loads(today_path.read_text(encoding="utf-8"))
        except Exception:
            raw = None

    if raw is None:
        found_date, raw = load_latest_narrative_snapshot(
            SNAPSHOT_DIR,
            today_str,
            max_lookback_days=LOOKBACK_DAYS,
            subject_key=subject,
        )
        if raw is None or found_date is None:
            return None
        snapshot_date = found_date

    parsed_date = _parse_snapshot_date(snapshot_date)
    if parsed_date is None:
        return None
    stale_days = (today - parsed_date).days
    if stale_days < 0 or stale_days > LOOKBACK_DAYS:
        return None

    try:
        state = NarrativeStateV1.model_validate(raw)
    except Exception:
        return None
    return _LoadedSnapshot(
        state=state,
        snapshot_date=snapshot_date,
        snapshot_subject=subject,
        stale_days=stale_days,
    )


def get_market_narrative_state() -> NarrativeStateV1 | None:
    loaded = _load_snapshot_for_subject("SPY")
    return loaded.state if loaded else None


def get_tech_narrative_state() -> NarrativeStateV1 | None:
    loaded = _load_snapshot_for_subject("QQQ")
    return loaded.state if loaded else None


def _loaded_snapshots() -> list[_LoadedSnapshot]:
    return [
        loaded
        for loaded in (_load_snapshot_for_subject("SPY"), _load_snapshot_for_subject("QQQ"))
        if loaded is not None
    ]


def _sector_etf_for_ticker(ticker: str) -> str | None:
    profile = get_ticker_profile(ticker)
    if not profile:
        return None
    value = profile.get("sector_etf")
    return normalize_ticker(str(value)) if value else None


def _narrative_tickers(narrative: DominantNarrative) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in narrative.tickers or []:
        ticker = normalize_ticker(str(raw))
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def _term_in_text(term: str, text: str) -> bool:
    term = str(term or "").strip()
    if not term:
        return False
    if len(term) <= 5 and term.upper() == term:
        return re.search(rf"(?<![A-Z0-9]){re.escape(term)}(?![A-Z0-9])", text.upper()) is not None
    return term.lower() in text.lower()


def _ticker_terms(ticker: str) -> list[str]:
    normalized = normalize_ticker(ticker)
    profile = get_ticker_profile(normalized)
    terms = [normalized]
    if profile:
        terms.extend(profile_terms(profile))
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        compact = str(term or "").strip()
        key = compact.lower()
        if compact and key not in seen:
            seen.add(key)
            out.append(compact)
    return out


def _ticker_in_evidence(ticker: str, narrative: DominantNarrative) -> bool:
    terms = _ticker_terms(ticker)
    for evidence in narrative.evidence or []:
        text = " ".join(
            str(part or "")
            for part in (evidence.title, evidence.source, evidence.channel, evidence.url)
        )
        if any(_term_in_text(term, text) for term in terms):
            return True
    return False


def _subject_matches(subject: str, key: str) -> bool:
    subject_text = str(subject or "").strip()
    if not subject_text:
        return False
    normalized_key = normalize_ticker(key)
    if normalize_ticker(subject_text) == normalized_key:
        return True
    return _term_in_text(normalized_key, subject_text)


def _find_inefficiency_for_subject(
    state: NarrativeStateV1,
    subject_key: str,
) -> InefficiencyMapItem | None:
    for item in state.inefficiency_map or []:
        if _subject_matches(item.subject, subject_key):
            return item
    return None


def _find_inefficiency_for_sector(
    state: NarrativeStateV1,
    sector_etf: str,
    sector_tickers: list[str],
) -> InefficiencyMapItem | None:
    direct = _find_inefficiency_for_subject(state, sector_etf)
    if direct:
        return direct
    for ticker in sector_tickers:
        found = _find_inefficiency_for_subject(state, ticker)
        if found:
            return found
    return None


def _is_default_archetype(archetype_id: str | None) -> bool:
    if not archetype_id:
        return False
    normalized = str(archetype_id).strip().lower().replace("-", "_").replace(" ", "_")
    return normalized == DEFAULT_ARCHETYPE_ID


def _narrative_summary(narrative: DominantNarrative) -> str | None:
    if narrative.why_now:
        return narrative.why_now
    if narrative.takeaways:
        return narrative.takeaways[0]
    return None


def _map_price_confirmation(value: str | None) -> PriceConfirmation | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if any(token in text for token in ("contradict", "refut", "not confirm")):
        return "contradicting"
    if any(token in text for token in ("partial", "mixed")):
        return "partial"
    if any(token in text for token in ("unavailable", "not enough", "unclear", "no price")):
        return "unavailable"
    if any(token in text for token in ("confirming", "confirmed", "confirms")):
        return "confirming"
    return None


def _price_confirmation(
    loaded: _LoadedSnapshot,
    narrative: DominantNarrative,
) -> PriceConfirmation | None:
    mapped = _map_price_confirmation(loaded.state.executive_snapshot.price_confirmation)
    if mapped:
        return mapped
    for line in narrative.takeaways or []:
        stripped = str(line or "").strip()
        if stripped.upper().startswith("PRICE:"):
            mapped = _map_price_confirmation(stripped)
            if mapped:
                return mapped
    return None


def _downgrade_quality_for_staleness(
    quality: CoverageQuality,
    stale_days: int,
) -> CoverageQuality:
    if stale_days <= 3:
        return quality
    if quality == "high":
        return "medium"
    if quality == "medium":
        return "low"
    if quality == "low":
        return "absent"
    return quality


def _empty_ticker_narrative(ticker: str, sector_etf: str | None) -> TickerNarrative:
    return TickerNarrative(
        ticker=ticker,
        coverage_quality="absent",
        sector_etf=sector_etf,
        sector_narrative_alignment="no_sector_signal",
        snapshot_date="",
    )


def _ticker_candidates(ticker: str) -> list[_NarrativeCandidate]:
    normalized = normalize_ticker(ticker)
    candidates: list[_NarrativeCandidate] = []
    for loaded in _loaded_snapshots():
        for idx, narrative in enumerate(loaded.state.dominant_narratives or []):
            if normalized not in _narrative_tickers(narrative):
                continue
            candidates.append(
                _NarrativeCandidate(
                    loaded=loaded,
                    narrative=narrative,
                    index=idx,
                    evidence_match=_ticker_in_evidence(normalized, narrative),
                    inefficiency=_find_inefficiency_for_subject(loaded.state, normalized),
                )
            )
    return candidates


def _select_ticker_candidate(ticker: str) -> _NarrativeCandidate | None:
    candidates = _ticker_candidates(ticker)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            item.evidence_match,
            item.confidence,
            item.has_specific_archetype,
            -item.index,
        ),
        reverse=True,
    )[0]


def _coverage_for_ticker_candidate(candidate: _NarrativeCandidate, ticker: str) -> CoverageQuality:
    same_snapshot_candidates = [
        item
        for item in _ticker_candidates(ticker)
        if item.loaded.snapshot_subject == candidate.loaded.snapshot_subject
        and item.loaded.snapshot_date == candidate.loaded.snapshot_date
    ]
    if candidate.confidence < 40:
        quality: CoverageQuality = "low"
    elif len(same_snapshot_candidates) >= 2 or any(item.evidence_match for item in same_snapshot_candidates):
        quality = "high"
    else:
        quality = "medium"
    return _downgrade_quality_for_staleness(quality, candidate.loaded.stale_days)


def _build_ticker_narrative(
    ticker: str,
    *,
    include_alignment: bool,
) -> TickerNarrative:
    normalized = normalize_ticker(ticker)
    sector_etf = _sector_etf_for_ticker(normalized)
    candidate = _select_ticker_candidate(normalized)
    if candidate is None:
        result = _empty_ticker_narrative(normalized, sector_etf)
        if include_alignment and sector_etf:
            sector = get_sector_narrative(sector_etf)
            if sector.coverage_quality not in {"absent", "low"}:
                result = result.model_copy(update={"sector_narrative_alignment": "no_sector_signal"})
        return result

    inefficiency = candidate.inefficiency
    quality = _coverage_for_ticker_candidate(candidate, normalized)
    result = TickerNarrative(
        ticker=normalized,
        coverage_quality=quality,
        dominant_narrative_title=candidate.narrative.title,
        dominant_narrative_summary=_narrative_summary(candidate.narrative),
        stance=candidate.narrative.stance,
        confidence=candidate.confidence,
        inefficiency_archetype_id=inefficiency.archetype_id if inefficiency else None,
        inefficiency_archetype_name=inefficiency.archetype if inefficiency else None,
        underlying_gap_type=inefficiency.underlying_gap_type if inefficiency else None,
        price_confirmation=_price_confirmation(candidate.loaded, candidate.narrative),
        sector_etf=sector_etf,
        snapshot_date=candidate.loaded.snapshot_date,
        snapshot_subject=candidate.loaded.snapshot_subject,
        is_stale=candidate.loaded.is_stale,
        source_narrative_indices=[
            item.index
            for item in _ticker_candidates(normalized)
            if item.loaded.snapshot_subject == candidate.loaded.snapshot_subject
            and item.loaded.snapshot_date == candidate.loaded.snapshot_date
        ],
    )

    if include_alignment:
        if not sector_etf:
            alignment: SectorAlignment = "no_sector_signal"
        else:
            sector = get_sector_narrative(sector_etf)
            if sector.coverage_quality in {"absent", "low"}:
                alignment = "no_sector_signal"
            else:
                divergence = detect_ticker_sector_divergence(normalized)
                if divergence is None:
                    alignment = "aligned"
                elif divergence.divergence_type == "idiosyncratic_story":
                    alignment = "idiosyncratic"
                else:
                    alignment = "diverging"
        result = result.model_copy(update={"sector_narrative_alignment": alignment})
    return result


def get_ticker_narrative(ticker: str) -> TickerNarrative:
    return _build_ticker_narrative(ticker, include_alignment=True)


def _sector_tickers_for_narrative(narrative: DominantNarrative, sector_etf: str) -> list[str]:
    requested = normalize_ticker(sector_etf)
    out: list[str] = []
    for ticker in _narrative_tickers(narrative):
        if ticker == requested or _sector_etf_for_ticker(ticker) == requested:
            out.append(ticker)
    return out


def _empty_sector_narrative(sector_etf: str) -> SectorNarrative:
    return SectorNarrative(
        sector_etf=normalize_ticker(sector_etf),
        coverage_quality="absent",
        snapshot_date="",
    )


def get_sector_narrative(sector_etf: str) -> SectorNarrative:
    requested = normalize_ticker(sector_etf)
    best: tuple[_LoadedSnapshot, DominantNarrative, int, list[str]] | None = None
    for loaded in _loaded_snapshots():
        for idx, narrative in enumerate(loaded.state.dominant_narratives or []):
            sector_tickers = _sector_tickers_for_narrative(narrative, requested)
            if len(sector_tickers) < 2:
                continue
            if best is None:
                best = (loaded, narrative, idx, sector_tickers)
                continue
            _, best_narrative, _, best_tickers = best
            if (len(sector_tickers), narrative.confidence) > (
                len(best_tickers),
                best_narrative.confidence,
            ):
                best = (loaded, narrative, idx, sector_tickers)

    if best is None:
        return _empty_sector_narrative(requested)

    loaded, narrative, _, sector_tickers = best
    if narrative.confidence < 40:
        quality: CoverageQuality = "low"
    elif len(sector_tickers) >= 3:
        quality = "high"
    else:
        quality = "medium"
    quality = _downgrade_quality_for_staleness(quality, loaded.stale_days)
    inefficiency = _find_inefficiency_for_sector(loaded.state, requested, sector_tickers)
    return SectorNarrative(
        sector_etf=requested,
        coverage_quality=quality,
        dominant_narrative_title=narrative.title,
        dominant_narrative_summary=_narrative_summary(narrative),
        stance=narrative.stance,
        confidence=narrative.confidence,
        sector_ticker_count=len(sector_tickers),
        sector_tickers_in_narrative=sector_tickers,
        inefficiency_archetype_id=inefficiency.archetype_id if inefficiency else None,
        snapshot_date=loaded.snapshot_date,
        snapshot_subject=loaded.snapshot_subject,
        is_stale=loaded.is_stale,
    )


def _opposite_stance(left: str | None, right: str | None) -> bool:
    return {left, right} == {"risk_on", "risk_off"}


def detect_ticker_sector_divergence(ticker: str) -> DivergenceSignal | None:
    normalized = normalize_ticker(ticker)
    ticker_narrative = _build_ticker_narrative(normalized, include_alignment=False)
    sector_etf = ticker_narrative.sector_etf
    if not sector_etf:
        return None
    sector_narrative = get_sector_narrative(sector_etf)
    if ticker_narrative.coverage_quality in {"absent", "low", "stale"}:
        return None
    if sector_narrative.coverage_quality in {"absent", "low", "stale"}:
        return None

    is_stale = ticker_narrative.is_stale or sector_narrative.is_stale
    snapshot_date = ticker_narrative.snapshot_date or sector_narrative.snapshot_date
    if _opposite_stance(ticker_narrative.stance, sector_narrative.stance):
        return DivergenceSignal(
            ticker=normalized,
            sector_etf=sector_etf,
            divergence_type="stance_opposite",
            ticker_stance=ticker_narrative.stance,
            sector_stance=sector_narrative.stance,
            ticker_archetype=ticker_narrative.inefficiency_archetype_id,
            sector_archetype=sector_narrative.inefficiency_archetype_id,
            rationale=(
                f"Ticker stance {ticker_narrative.stance} contradicts sector "
                f"{sector_etf} narrative stance {sector_narrative.stance} as of "
                f"{snapshot_date} snapshot."
            ),
            snapshot_date=snapshot_date,
            is_stale=is_stale,
        )

    ticker_archetype = ticker_narrative.inefficiency_archetype_id
    sector_archetype = sector_narrative.inefficiency_archetype_id
    if (
        ticker_archetype
        and sector_archetype
        and ticker_archetype != sector_archetype
        and not _is_default_archetype(ticker_archetype)
        and not _is_default_archetype(sector_archetype)
    ):
        return DivergenceSignal(
            ticker=normalized,
            sector_etf=sector_etf,
            divergence_type="archetype_mismatch",
            ticker_stance=ticker_narrative.stance,
            sector_stance=sector_narrative.stance,
            ticker_archetype=ticker_archetype,
            sector_archetype=sector_archetype,
            rationale=(
                f"Ticker archetype {ticker_archetype} differs from sector "
                f"{sector_etf} archetype {sector_archetype} as of {snapshot_date} snapshot."
            ),
            snapshot_date=snapshot_date,
            is_stale=is_stale,
        )

    candidate = _select_ticker_candidate(normalized)
    if candidate is None:
        return None
    narrative_tickers = _narrative_tickers(candidate.narrative)
    if narrative_tickers:
        same_sector_count = sum(
            1
            for item in narrative_tickers
            if item == sector_etf or _sector_etf_for_ticker(item) == sector_etf
        )
        same_sector_share = same_sector_count / len(narrative_tickers)
        if same_sector_share < 0.30:
            return DivergenceSignal(
                ticker=normalized,
                sector_etf=sector_etf,
                divergence_type="idiosyncratic_story",
                ticker_stance=ticker_narrative.stance,
                sector_stance=sector_narrative.stance,
                ticker_archetype=ticker_archetype,
                sector_archetype=sector_archetype,
                rationale=(
                    f"{normalized} appears in a narrative where only "
                    f"{same_sector_count}/{len(narrative_tickers)} tickers share "
                    f"sector {sector_etf}, making the story idiosyncratic as of "
                    f"{snapshot_date} snapshot."
                ),
                snapshot_date=snapshot_date,
                is_stale=is_stale,
            )

    return None
