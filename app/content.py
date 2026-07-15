"""Scenario content pack loader and validation.

Loads the authored YAML market (``content/scenario_meridian.yaml``) into typed
dataclasses and validates it hard at load time — a malformed pack fails loudly
at seed time rather than mid-demo (plan U2). The dataclasses are the single
shared contract the deterministic engine (U3) and feedback service (U5) read.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

DEFAULT_PACK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "content",
    "scenario_meridian.yaml",
)

# The reserved allocation key for uninvested cash (shared across engine,
# routes, and scoring so the allocation contract lives in one place).
CASH_ID = "CASH"

# Outcome categories for authored fallback coaching (plan R6).
FEEDBACK_CATEGORIES = ("beat_kept", "beat_breached", "trailed_kept", "trailed_breached")

# Badge ids requiring an authored fallback citation (U9). Declared here rather
# than imported from ``app.badges`` because badges depends on this module; a
# test asserts the two lists stay in step.
BADGE_IDS = (
    "market_beater",
    "crisis_navigator",
    "sharp_read",
    "mandate_keeper",
    "alpha_generator",
    "trusted_advisor",
    "diversifier",
    "deep_thinker",
)


class ContentError(ValueError):
    """Raised when the scenario pack is missing or structurally invalid."""


@dataclass(frozen=True)
class SharePrice:
    price: float
    why: str


@dataclass(frozen=True)
class Share:
    id: str
    name: str
    sector: str
    start_price: float
    rounds: list[SharePrice]  # index 0 == round 1 end price

    def price_at_start_of_round(self, round_number: int) -> float:
        """Price the student allocates at when round ``round_number`` opens."""
        if round_number == 1:
            return self.start_price
        return self.rounds[round_number - 2].price

    def price_at_end_of_round(self, round_number: int) -> float:
        return self.rounds[round_number - 1].price

    def return_in_round(self, round_number: int) -> float:
        """Fractional price return during a round (e.g. 0.06 for +6%)."""
        start = self.price_at_start_of_round(round_number)
        end = self.price_at_end_of_round(round_number)
        return (end / start) - 1.0

    def why_for_round(self, round_number: int) -> str:
        return self.rounds[round_number - 1].why


@dataclass(frozen=True)
class Mandate:
    summary: str
    risk_tolerance: str
    max_single_share_pct: float
    min_cash_pct: float
    guidance: str = ""


@dataclass(frozen=True)
class Client:
    name: str
    persona: str
    mandate: Mandate


@dataclass(frozen=True)
class Event:
    id: str
    round: int
    title: str
    narrative: str
    affected_shares: list[str]


@dataclass(frozen=True)
class Brief:
    round: int
    headline: str
    body: str
    sector_news: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Fallback:
    feedback: dict[str, str]
    reflection_prompts: list[str]
    # Authored citation per badge id — used offline and whenever the live
    # citation call fails, so an earned credential always reads as earned.
    badge_citations: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentPack:
    title: str
    currency: str
    starting_capital: float
    total_rounds: int
    starting_trust: float
    client: Client
    shares: list[Share]
    events: list[Event]
    briefs: list[Brief]
    fallback: Fallback

    @property
    def sectors(self) -> list[str]:
        return [s.sector for s in self.shares]

    def share_by_id(self, share_id: str) -> Share:
        for share in self.shares:
            if share.id == share_id:
                return share
        raise KeyError(share_id)

    def brief_for_round(self, round_number: int) -> Brief:
        for brief in self.briefs:
            if brief.round == round_number:
                return brief
        raise KeyError(round_number)

    def events_for_round(self, round_number: int) -> list[Event]:
        return [e for e in self.events if e.round == round_number]

    def benchmark_return_in_round(self, round_number: int) -> float:
        """Equal-weight index return across all shares for a round."""
        return sum(s.return_in_round(round_number) for s in self.shares) / len(self.shares)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContentError(message)


def _validate(pack: ContentPack) -> None:
    _require(pack.total_rounds >= 1, "total_rounds must be at least 1")
    _require(len(pack.shares) >= 1, "the pack must define at least one share")
    _require(pack.starting_capital > 0, "starting_capital must be positive")

    ids = [s.id for s in pack.shares]
    _require(len(ids) == len(set(ids)), f"share ids must be unique, got {ids}")

    for share in pack.shares:
        _require(share.start_price > 0, f"share '{share.id}' needs a positive start_price")
        _require(
            len(share.rounds) == pack.total_rounds,
            f"share '{share.id}' has {len(share.rounds)} round prices but total_rounds is {pack.total_rounds}",
        )
        for idx, sp in enumerate(share.rounds, start=1):
            _require(sp.price > 0, f"share '{share.id}' round {idx} price must be positive")
            _require(bool(sp.why.strip()), f"share '{share.id}' round {idx} is missing a 'why' rationale")

    for rnd in range(1, pack.total_rounds + 1):
        matches = [b for b in pack.briefs if b.round == rnd]
        _require(len(matches) == 1, f"expected exactly one brief for round {rnd}, found {len(matches)}")

    known = set(ids)
    for event in pack.events:
        _require(
            1 <= event.round <= pack.total_rounds,
            f"event '{event.id}' references round {event.round}, outside 1..{pack.total_rounds}",
        )
        for sid in event.affected_shares:
            _require(
                sid in known,
                f"event '{event.id}' references unknown share '{sid}'",
            )

    mandate = pack.client.mandate
    _require(
        0 < mandate.max_single_share_pct <= 100,
        "mandate.max_single_share_pct must be within (0, 100]",
    )
    _require(0 <= mandate.min_cash_pct < 100, "mandate.min_cash_pct must be within [0, 100)")

    for category in FEEDBACK_CATEGORIES:
        _require(
            category in pack.fallback.feedback and bool(pack.fallback.feedback[category].strip()),
            f"fallback.feedback is missing authored text for '{category}'",
        )
    _require(
        len(pack.fallback.reflection_prompts) >= pack.total_rounds,
        f"fallback.reflection_prompts needs at least {pack.total_rounds} entries",
    )

    for badge_id in BADGE_IDS:
        _require(
            badge_id in pack.fallback.badge_citations
            and bool(pack.fallback.badge_citations[badge_id].strip()),
            f"fallback.badge_citations is missing authored text for '{badge_id}'",
        )


def _parse(raw: dict) -> ContentPack:
    try:
        shares = [
            Share(
                id=str(s["id"]),
                name=s["name"],
                sector=s["sector"],
                start_price=float(s["start_price"]),
                rounds=[SharePrice(price=float(r["price"]), why=str(r["why"])) for r in s["rounds"]],
            )
            for s in raw["shares"]
        ]
        events = [
            Event(
                id=str(e["id"]),
                round=int(e["round"]),
                title=e["title"],
                narrative=e["narrative"],
                affected_shares=[str(x) for x in e.get("affected_shares", [])],
            )
            for e in raw.get("events", [])
        ]
        briefs = [
            Brief(
                round=int(b["round"]),
                headline=b["headline"],
                body=b["body"],
                sector_news=list(b.get("sector_news", [])),
            )
            for b in raw["briefs"]
        ]
        mandate_raw = raw["client"]["mandate"]
        client = Client(
            name=raw["client"]["name"],
            persona=raw["client"]["persona"],
            mandate=Mandate(
                summary=mandate_raw["summary"],
                risk_tolerance=mandate_raw["risk_tolerance"],
                max_single_share_pct=float(mandate_raw["max_single_share_pct"]),
                min_cash_pct=float(mandate_raw["min_cash_pct"]),
                guidance=mandate_raw.get("guidance", ""),
            ),
        )
        fallback = Fallback(
            feedback={k: str(v) for k, v in raw["fallback"]["feedback"].items()},
            reflection_prompts=[str(p) for p in raw["fallback"]["reflection_prompts"]],
            badge_citations={
                k: str(v) for k, v in (raw["fallback"].get("badge_citations") or {}).items()
            },
        )
        pack = ContentPack(
            title=raw["title"],
            currency=raw["currency"],
            starting_capital=float(raw["starting_capital"]),
            total_rounds=int(raw["total_rounds"]),
            starting_trust=float(raw.get("starting_trust", 50)),
            client=client,
            shares=shares,
            events=events,
            briefs=briefs,
            fallback=fallback,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContentError(f"scenario pack is malformed: {exc}") from exc
    return pack


def load_content_pack(path: str | None = None) -> ContentPack:
    """Load, parse, and validate the scenario pack. Raises ``ContentError``."""
    path = path or os.environ.get("CONTENT_PACK", DEFAULT_PACK_PATH)
    if not os.path.exists(path):
        raise ContentError(f"scenario pack not found at '{path}'")
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ContentError("scenario pack must be a YAML mapping at the top level")
    pack = _parse(raw)
    _validate(pack)
    return pack
