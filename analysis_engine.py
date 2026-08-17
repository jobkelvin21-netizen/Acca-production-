"""
analysis_engine.py - BOT A
Movement + probability edge signal (no invented formula - uses SportyBet's own
probability field, compared against its earliest recorded snapshot for that
outcome). Builds 3-leg accas with a HARD tight-kickoff-window rule. Verifies
(90+, constant). Ranks verified candidates: prefers 15+ combined when
available, otherwise strongest movement signal overall. Only #1 surfaced.
"""

import logging
import uuid
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from itertools import combinations
from config import config
import database as db

logger = logging.getLogger("analysis_engine_a")


class MovementChecker:
    """
    Compares each leg's current probability against its recorded history.
    TIGHTENED: requires at least MIN_SNAPSHOT_COUNT readings, and requires the
    trend to be broadly CONSISTENT (not just a single noisy spike that nets
    positive between two points) - a real sustained rise, checked across
    every consecutive pair of readings, not just start vs end.
    """

    @staticmethod
    def check_leg(leg: Dict) -> Tuple[bool, float, str]:
        event_id = leg["event_id"]
        market_id = leg["market_id"]
        outcome_id = leg["outcome_id"]
        current_prob = leg["current_probability"]

        db.Database.save_snapshot(event_id, market_id, outcome_id, leg["odds"], current_prob)

        history = db.Database.get_snapshot_history(event_id, market_id, outcome_id)
        if len(history) < config.MIN_SNAPSHOT_COUNT:
            return False, 0.0, f"Only {len(history)} reading(s) so far (need {config.MIN_SNAPSHOT_COUNT}+ for a reliable trend)"

        earliest = history[0]
        latest = history[-1]

        try:
            earliest_time = datetime.fromisoformat(earliest["snapshot_time"])
            hours_gap = (datetime.now() - earliest_time).total_seconds() / 3600
        except Exception:
            return False, 0.0, "Snapshot timestamp error"

        if hours_gap < config.MIN_SNAPSHOT_GAP_HOURS:
            return False, 0.0, f"Only {hours_gap:.1f}h of history (need {config.MIN_SNAPSHOT_GAP_HOURS}h+)"

        earliest_prob = earliest.get("probability", 0.0)
        increase = current_prob - earliest_prob

        # CONSISTENCY CHECK: require the trend to be broadly non-decreasing across
        # readings, not a single spike. Allow small noise (up to 2 points dip
        # between any two consecutive readings) but reject anything that swings
        # wildly - that's noise, not a real sustained trend.
        for i in range(1, len(history)):
            step_change = history[i]["probability"] - history[i - 1]["probability"]
            if step_change < -0.02:
                return False, increase, (f"Inconsistent trend - probability dropped "
                                          f"{abs(step_change):.1%} between two readings "
                                          f"(real movement should be broadly steady, not spiky)")

        if current_prob < config.MIN_CURRENT_PROBABILITY:
            return False, increase, f"Current probability {current_prob:.1%} below minimum {config.MIN_CURRENT_PROBABILITY:.0%} (must be more likely than not)"

        if increase < config.MIN_PROBABILITY_INCREASE:
            return False, increase, f"Probability moved {increase:+.1%} (need +{config.MIN_PROBABILITY_INCREASE:.0%} or more)"

        reasoning = (f"{leg['selection']}: {earliest_prob:.1%} → {current_prob:.1%} "
                     f"({increase:+.1%} over {hours_gap:.1f}h, {len(history)} consistent readings) | odds {leg['odds']}")
        return True, increase, reasoning


class AccumulatorBuilder:

    @staticmethod
    def _same_team_or_event(leg1: Dict, leg2: Dict) -> bool:
        return leg1.get("event_id") == leg2.get("event_id") or leg1.get("team_id") == leg2.get("team_id")

    @staticmethod
    def _within_kickoff_window(legs: List[Dict]) -> bool:
        """HARD RULE: all legs in one acca must kick off within KICKOFF_WINDOW_HOURS of each other."""
        try:
            times = [datetime.fromisoformat(l["kickoff_time"]) for l in legs]
            spread_hours = (max(times) - min(times)).total_seconds() / 3600
            return spread_hours <= config.KICKOFF_WINDOW_HOURS
        except Exception:
            return False

    @staticmethod
    def build_candidates(qualifying_legs: List[Dict]) -> List[Dict]:
        """qualifying_legs = only legs that already passed the movement check."""
        candidates = []
        for combo in combinations(qualifying_legs[:25], config.LEGS_PER_ACCA):
            if not config.ALLOW_CORRELATED_LEGS:
                if any(AccumulatorBuilder._same_team_or_event(combo[i], combo[j])
                       for i in range(len(combo)) for j in range(i + 1, len(combo))):
                    continue

            # HARD TIGHT-WINDOW CHECK - never skipped, never relaxed
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

        logger.info(f"✅ Built {len(candidates)} candidate accas "
                    f"(tight {config.KICKOFF_WINDOW_HOURS}h kickoff window enforced, "
                    f"{config.MIN_ODDS_PER_LEG}+ per leg)")
        return candidates


class Verifier:
    """5-check verification, 90+ required, no partial credit."""

    @staticmethod
    def verify_all(candidates: List[Dict]) -> List[Dict]:
        verified = []
        for acca in candidates:
            score, reasoning = Verifier._verify_acca(acca)
            if score >= config.MIN_VERIFICATION_SCORE:
                acca["verification_score"] = score
                acca["reasoning"] = reasoning
                acca["recommended_stake"] = config.get_recommended_bet_size()
                verified.append(acca)
        logger.info(f"✅ Verified {len(verified)} accas at {config.MIN_VERIFICATION_SCORE}+/100")
        return verified

    @staticmethod
    def _verify_acca(acca: Dict) -> Tuple[int, str]:
        """
        Graduated scoring: each check contributes a RANGE of points based on
        HOW STRONGLY it passes, not just pass/fail. A pick can genuinely score
        90, 94, or 100 depending on real signal strength - not just 0 or 100.
        Still hard-fails (returns 0) on the non-negotiable structural rules
        (kickoff window, correlation, market support) since those aren't
        "strength" questions - they're yes/no rules.
        """
        legs = acca["legs"]

        # HARD STRUCTURAL RULES - fail completely, no partial credit here.
        # These are not "how strong" questions, they're "is this even valid" questions.
        if not all(l.get("kickoff_time") for l in legs):
            return 0, ""
        if not AccumulatorBuilder._within_kickoff_window(legs):
            return 0, ""
        if any(AccumulatorBuilder._same_team_or_event(legs[i], legs[j])
               for i in range(len(legs)) for j in range(i + 1, len(legs))):
            return 0, ""
        if not all(l["odds"] >= config.MIN_ODDS_PER_LEG for l in legs):
            return 0, ""
        if not all(l.get("_movement_passed") for l in legs):
            return 0, ""

        # GRADUATED SCORING - SportyBet's own probability is the TRUE primary
        # signal. Movement can only ADD to a genuinely decent probability, it
        # can never compensate for a weak one - this is deliberate, not
        # additive, so a big movement on a weak pick can't outscore a strong
        # probability with modest movement.
        score = 30  # base score once all structural rules pass

        probs = [l.get("current_probability", 0) for l in legs]
        avg_prob = sum(probs) / len(probs) if probs else 0
        # scaled from the REAL qualifying floor (config value) up to a strong 75% -
        # references config directly so this can never drift out of sync with the
        # actual filter threshold again
        prob_ratio = min(1.0, max(0.0, (avg_prob - config.MIN_CURRENT_PROBABILITY) / (0.75 - config.MIN_CURRENT_PROBABILITY)))
        prob_points = 45 * prob_ratio  # PRIMARY signal - up to 45 pts

        increases = [l.get("_movement_increase", 0) for l in legs]
        avg_increase = sum(increases) / len(increases) if increases else 0
        movement_ratio = min(1.0, avg_increase / 0.20) if avg_increase > 0 else 0
        # movement bonus is SCALED BY probability strength too - a huge movement
        # on a weak-probability pick earns little, because movement_ratio alone
        # isn't enough; it needs decent probability underneath it as well
        movement_points = 20 * movement_ratio * max(0.3, prob_ratio)

        score += round(prob_points)
        score += round(movement_points)

        # Kickoff tightness (up to 5 pts) - minor safety consideration only
        try:
            times = [datetime.fromisoformat(l["kickoff_time"]) for l in legs]
            spread_hours = (max(times) - min(times)).total_seconds() / 3600
            tightness_ratio = 1 - (spread_hours / config.KICKOFF_WINDOW_HOURS)
            score += round(5 * max(0, tightness_ratio))
        except Exception:
            pass

        score = min(100, max(0, score))

        reasoning = " || ".join(l.get("_movement_reasoning", "") for l in legs)
        return score, reasoning


class DailyPickSelector:
    """
    Among all verified candidates: prefer ones at/above the 15+ target;
    among those, pick the strongest average movement signal. If nothing
    reaches 15+, fall back to the strongest-signal verified pick overall.
    Only #1 is ever returned.
    """

    @staticmethod
    def get_best_pick(verified_accas: List[Dict]) -> Optional[Dict]:
        if not verified_accas:
            logger.warning("❌ No verified accas today - nothing shown, this is normal.")
            return None

        def avg_movement(acca):
            increases = [l.get("_movement_increase", 0) for l in acca["legs"]]
            return sum(increases) / len(increases) if increases else 0

        near_target = [a for a in verified_accas if a["combined_odds"] >= config.TARGET_COMBINED_ODDS]
        pool = near_target if near_target else verified_accas

        ranked = sorted(pool, key=avg_movement, reverse=True)
        best = ranked[0]

        logger.info(f"\n{'='*80}")
        logger.info(f"🏆 TODAY'S #1 PICK")
        logger.info(f"{'='*80}")
        logger.info(f"ID: {best['id']}")
        logger.info(f"Combined Odds: {best['combined_odds']} (target was {config.TARGET_COMBINED_ODDS}+)")
        logger.info(f"Verification Score: {best['verification_score']}/100")
        logger.info(f"Reasoning: {best['reasoning']}")
        logger.info(f"Recommended Stake: ₦{best['recommended_stake']:,.0f}")
        logger.info(f"{'='*80}\n")

        return best
