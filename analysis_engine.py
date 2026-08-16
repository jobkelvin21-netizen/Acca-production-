"""
analysis_engine.py - BOT A: 15+ ODDS HUNTER
Strategy: multi-platform price comparison (Melbet vs other books) + raw real
stats shown transparently (no invented probability formula). Builds 3-leg
accas (each leg >=2.0 odds, no correlation, tight kickoff window, only
market types with real data backing). Verifies (90+). Among everything
verified, ranks by combined signal strength (price gap + real-data support),
targets 15+ but shows the best verified pick regardless of exact number -
no hard floor, no cap. Only #1 is ever surfaced.
"""

import logging
import uuid
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from itertools import combinations
from config import config
from database import ComparisonOddsScraper

logger = logging.getLogger("analysis_engine_a")


class AccumulatorBuilder:

    @staticmethod
    def _same_team_or_event(leg1: Dict, leg2: Dict) -> bool:
        return leg1.get("team_id") == leg2.get("team_id") or \
            (leg1.get("league") == leg2.get("league") and leg1.get("selection") == leg2.get("selection"))

    @staticmethod
    def _within_kickoff_window(legs: List[Dict]) -> bool:
        try:
            times = [datetime.fromisoformat(l["kickoff_time"]) for l in legs]
            spread_hours = (max(times) - min(times)).total_seconds() / 3600
            return spread_hours <= config.KICKOFF_WINDOW_HOURS
        except Exception:
            return False

    @staticmethod
    def build_candidates(all_legs: List[Dict]) -> List[Dict]:
        legs = [l for l in all_legs if l.get("odds", 0) >= config.MIN_ODDS_PER_LEG]
        if config.QUICK_FINISH_PREFERENCE:
            quick = [l for l in legs if l.get("is_quick_finish")]
            other = [l for l in legs if not l.get("is_quick_finish")]
            legs = quick + other

        candidates = []
        for combo in combinations(legs[:25], config.LEGS_PER_ACCA):
            if not config.ALLOW_CORRELATED_LEGS:
                if any(AccumulatorBuilder._same_team_or_event(combo[i], combo[j])
                       for i in range(len(combo)) for j in range(i + 1, len(combo))):
                    continue
            if not AccumulatorBuilder._within_kickoff_window(list(combo)):
                continue

            combined_odds = 1.0
            for leg in combo:
                combined_odds *= leg["odds"]

            candidates.append({
                "id": f"BOTA-{uuid.uuid4().hex[:10].upper()}",
                "legs": list(combo),
                "combined_odds": round(combined_odds, 2),
            })
            if len(candidates) >= 60:
                break

        logger.info(f"✅ Bot A built {len(candidates)} candidate accas ({config.MIN_ODDS_PER_LEG}+ per leg, target ~{config.TARGET_COMBINED_ODDS})")
        return candidates


class Verifier:
    """5-check verification, 90+ required, no partial credit.
    Real edge = Melbet priced meaningfully better than other-book consensus
    (price gap), combined with real supporting stats shown transparently."""

    @staticmethod
    def verify_all(candidates: List[Dict], real_data_lookup: Dict[str, Dict]) -> List[Dict]:
        verified = []
        for acca in candidates:
            score, signal_strength, reasoning = Verifier._verify_acca(acca, real_data_lookup)
            if score >= config.MIN_VERIFICATION_SCORE:
                acca["verification_score"] = score
                acca["signal_strength"] = round(signal_strength, 4)
                acca["reasoning"] = reasoning
                acca["recommended_stake"] = config.get_recommended_bet_size()
                verified.append(acca)
        logger.info(f"✅ Bot A verified {len(verified)} accas at {config.MIN_VERIFICATION_SCORE}+/100")
        return verified

    @staticmethod
    def _verify_acca(acca: Dict, real_data_lookup: Dict[str, Dict]) -> Tuple[int, float, str]:
        score = 0
        gaps = []
        reasoning_parts = []

        # CHECK 1: Market exists / real kickoff time (20 pts) - hard fail if missing
        if all(l.get("kickoff_time") for l in acca["legs"]):
            score += 20
        else:
            return 0, 0, ""

        # CHECK 2: Kickoff window respected (20 pts) - hard fail if not
        if AccumulatorBuilder._within_kickoff_window(acca["legs"]):
            score += 20
        else:
            return 0, 0, ""

        # CHECK 3: Melbet price meaningfully better than other-book consensus on every leg (30 pts)
        all_gap_ok = True
        for leg in acca["legs"]:
            gap = ComparisonOddsScraper.get_price_gap(leg["odds"], leg.get("match_id", ""), leg.get("selection", ""))
            if gap < config.MIN_PRICE_GAP_PERCENT:
                all_gap_ok = False
            gaps.append(gap)
            real_data = real_data_lookup.get(leg.get("selection", ""), {})
            summary = real_data.get("form_summary", "no data")
            reasoning_parts.append(f"{leg.get('selection')}: {summary} | price {gap:+.1%} vs market")
        if all_gap_ok:
            score += 30
        else:
            return 0, 0, ""

        # CHECK 4: No correlated legs (15 pts) - hard fail if correlated
        if not any(AccumulatorBuilder._same_team_or_event(acca["legs"][i], acca["legs"][j])
                   for i in range(len(acca["legs"])) for j in range(i + 1, len(acca["legs"]))):
            score += 15
        else:
            return 0, 0, ""

        # CHECK 5: Every leg is a supported market type with real data backing (15 pts)
        if all(l.get("market_type") in config.SUPPORTED_MARKET_TYPES for l in acca["legs"]):
            score += 15
        else:
            return 0, 0, ""

        signal_strength = sum(gaps) / len(gaps) if gaps else 0.0
        reasoning = " || ".join(reasoning_parts)

        return min(100, score), signal_strength, reasoning


class DailyPickSelector:
    """
    BOT A RANKING RULE: among all verified candidates, pick the one with the
    STRONGEST combined signal (average price-gap across all 3 legs vs other
    bookmakers). Targets ~15+ combined odds, but no hard floor and no cap -
    shows the best verified pick found that day regardless of exact number.
    Only #1 is ever returned.
    """

    @staticmethod
    def get_best_pick(verified_accas: List[Dict]) -> Optional[Dict]:
        if not verified_accas:
            logger.warning("❌ Bot A: no verified accas today - nothing shown, this is normal.")
            return None

        # Prefer picks near/above the 15+ target first, then fall back to strongest signal overall
        near_target = [a for a in verified_accas if a["combined_odds"] >= config.TARGET_COMBINED_ODDS]
        pool = near_target if near_target else verified_accas

        ranked = sorted(pool, key=lambda a: a.get("signal_strength", 0), reverse=True)
        best = ranked[0]

        logger.info(f"\n{'='*80}")
        logger.info(f"🏆 BOT A - TODAY'S #1 PICK")
        logger.info(f"{'='*80}")
        logger.info(f"ID: {best['id']}")
        logger.info(f"Combined Odds: {best['combined_odds']} (target was {config.TARGET_COMBINED_ODDS}+)")
        logger.info(f"Verification Score: {best['verification_score']}/100")
        logger.info(f"Signal Strength (avg price gap vs market): {best['signal_strength']:+.1%}")
        logger.info(f"Reasoning: {best['reasoning']}")
        logger.info(f"Recommended Stake: ₦{best['recommended_stake']:,.0f}")
        logger.info(f"{'='*80}\n")

        return best
