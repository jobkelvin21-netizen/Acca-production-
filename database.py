"""
database.py - BOT A
Direct SportyBet scraping against confirmed real endpoints (no Parse.bot,
no other API keys). Also handles Supabase storage for picks, snapshots,
placements, results, and the outcome log.
"""

import logging
import requests
from datetime import datetime
from typing import List, Dict, Optional
from supabase import create_client, Client
from config import config

logger = logging.getLogger("database_a")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


class Database:
    _client: Optional[Client] = None

    @staticmethod
    def connect() -> Client:
        if Database._client is None:
            Database._client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
            logger.info("✅ Connected to Supabase (Bot A)")
        return Database._client

    @staticmethod
    def init_tables():
        logger.info("✅ Assuming tables exist: verified_accumulators_a, user_placements_a, "
                     "verified_results_a, pick_log_a, odds_snapshots_a")

    @staticmethod
    def save_snapshot(event_id: str, market_id: str, outcome_id: str,
                       odds: float, probability: float) -> bool:
        """Store one odds/probability reading for later movement comparison."""
        try:
            dbc = Database.connect()
            dbc.table("odds_snapshots_a").insert({
                "event_id": event_id, "market_id": market_id, "outcome_id": outcome_id,
                "odds": odds, "probability": probability,
                "snapshot_time": datetime.now().isoformat(),
            }).execute()
            return True
        except Exception as e:
            logger.warning(f"Snapshot save failed ({event_id}/{market_id}/{outcome_id}): {e}")
            return False

    @staticmethod
    def get_earliest_snapshot(event_id: str, market_id: str, outcome_id: str) -> Optional[Dict]:
        """Get the first recorded snapshot for this outcome (for movement comparison)."""
        try:
            dbc = Database.connect()
            result = dbc.table("odds_snapshots_a").select("*").eq(
                "event_id", event_id).eq("market_id", market_id).eq(
                "outcome_id", outcome_id).order("snapshot_time", desc=False).limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(f"Get earliest snapshot failed: {e}")
            return None

    @staticmethod
    def supersede_old_picks(new_pick_id: str) -> bool:
        """
        Marks any previously 'pending' picks as 'superseded' before a new
        pick is saved, so the table never has more than one truly active
        pending pick at a time - not just relying on dashboards to sort by
        newest.
        """
        try:
            dbc = Database.connect()
            dbc.table("verified_accumulators_a").update(
                {"status": "superseded"}
            ).eq("status", "pending").neq("id", new_pick_id).execute()
            logger.info("✅ Old pending picks marked as superseded")
            return True
        except Exception as e:
            logger.warning(f"Supersede step failed (non-critical): {e}")
            return False

    @staticmethod
    def save_verified_accumulator(acca: Dict) -> bool:
        """Saves the SINGLE #1 pick of the day. Confirmed by readback.
        Also supersedes any older pending picks so only one is ever active."""
        try:
            dbc = Database.connect()
            payload = {
                "id": acca["id"],
                "legs": acca["legs"],
                "combined_odds": acca["combined_odds"],
                "verification_score": acca["verification_score"],
                "reasoning": acca.get("reasoning"),
                "recommended_stake": acca.get("recommended_stake"),
                "status": "pending",
                "created_at": datetime.now().isoformat(),
            }
            insert_result = dbc.table("verified_accumulators_a").insert(payload).execute()
            if not insert_result.data:
                logger.error("❌ SUPABASE WRITE FAILED - insert returned no data")
                return False

            confirm = dbc.table("verified_accumulators_a").select("id").eq("id", acca["id"]).execute()
            if confirm.data:
                logger.info(f"✅ CONFIRMED IN SUPABASE: pick {acca['id']} saved and readable")

                # Supersede any older pending picks now that the new one is confirmed saved
                Database.supersede_old_picks(acca["id"])

                try:
                    dbc.table("pick_log_a").insert({
                        "accumulator_id": acca["id"], "reasoning": acca.get("reasoning"),
                        "combined_odds": acca["combined_odds"],
                        "verification_score": acca["verification_score"],
                        "created_at": datetime.now().isoformat(),
                    }).execute()
                except Exception as e:
                    logger.warning(f"Pick log write failed (non-critical): {e}")
                return True
            logger.error(f"❌ SUPABASE WRITE UNVERIFIED - row {acca['id']} not found on readback")
            return False
        except Exception as e:
            logger.error(f"❌ SUPABASE SAVE ERROR: {e}")
            return False


def get_daily_top_acca() -> Optional[Dict]:
    try:
        dbc = Database.connect()
        result = dbc.table("verified_accumulators_a").select("*").eq(
            "status", "pending").order("created_at", desc=True).limit(1).execute()
        acca = result.data[0] if result.data else None
        if acca:
            logger.info(f"✅ Retrieved pending pick: {acca.get('id')}")
        else:
            logger.warning("⚠️ No pending pick found in Supabase.")
        return acca
    except Exception as e:
        logger.error(f"Get #1 acca error: {e}")
        return None


# ============================================================================
# DIRECT SPORTYBET SCRAPER (confirmed real endpoints, verified via network inspection)
# ============================================================================

class SportyBetScraper:

    @staticmethod
    def get_upcoming_matches(sport_key: str = "football") -> List[Dict]:
        """
        Real endpoint: pcUpcomingEvents?sportId=sr:sport:1&marketId=...&pageSize=100
        &pageNum=1&todayGames=true
        Returns list of {event_id, tournament_name, category_name} for eligible
        (non-excluded-league) matches, pre-match only.
        """
        try:
            sport_id = config.SPORT_IDS.get(sport_key)
            if not sport_id:
                logger.warning(f"No sport_id configured for '{sport_key}'")
                return []

            params = {
                "sportId": sport_id,
                "marketId": config.FOOTBALL_MARKET_IDS,
                "pageSize": 100,
                "pageNum": 1,
                "todayGames": "true",
            }
            response = requests.get(config.SPORTYBET_LIST_URL, params=params,
                                     headers=HEADERS, timeout=12)
            response.raise_for_status()
            data = response.json()

            tournaments = data.get("data", {}).get("tournaments", [])
            matches = []
            for tournament in tournaments:
                tname = (tournament.get("name") or "").lower()
                cname = (tournament.get("categoryName") or "").lower()

                # SLOPPY MARKET FILTER: skip the most heavily-bet leagues
                if any(excl in tname or excl in cname for excl in config.EXCLUDED_LEAGUES):
                    continue

                for event in tournament.get("events", []):
                    event_id = event.get("eventId")
                    if not event_id:
                        continue
                    matches.append({
                        "event_id": event_id,
                        "tournament_name": tournament.get("name"),
                        "category_name": tournament.get("categoryName"),
                        "sport": sport_key,
                    })

            logger.info(f"✅ SportyBet {sport_key}: {len(matches)} candidate matches "
                        f"(after excluding heavily-bet leagues)")
            return matches
        except Exception as e:
            logger.warning(f"SportyBet upcoming matches error ({sport_key}): {e}")
            return []

    @staticmethod
    def get_event_detail(event_id: str) -> Optional[Dict]:
        """
        Real endpoint: event?eventId=sr:match:XXXXX
        Returns full match detail: homeTeamName, awayTeamName, estimateStartTime,
        matchStatus, markets[] each with outcomes[] carrying id/odds/probability/
        lastOddsChangeTime.
        """
        try:
            params = {"eventId": event_id}
            response = requests.get(config.SPORTYBET_EVENT_URL, params=params,
                                     headers=HEADERS, timeout=12)
            response.raise_for_status()
            data = response.json()
            match = data.get("data")
            if not match:
                return None

            if match.get("matchStatus", "").lower() != "not start":
                return None  # pre-match only, hard reject anything already live/started

            return match
        except Exception as e:
            logger.warning(f"SportyBet event detail error ({event_id}): {e}")
            return None

    @staticmethod
    def extract_legs(match: Dict) -> List[Dict]:
        """
        Turn one match's raw detail into a list of candidate legs - one per
        outcome, restricted to SUPPORTED_MARKET_IDS only.
        """
        legs = []
        event_id = match.get("eventId")
        home = match.get("homeTeamName")
        away = match.get("awayTeamName")
        start_time_ms = match.get("estimateStartTime")
        if not (event_id and home and away and start_time_ms):
            return legs

        kickoff_iso = datetime.fromtimestamp(start_time_ms / 1000).isoformat()

        for market in match.get("markets", []):
            market_id = str(market.get("id", ""))
            if market_id not in config.SUPPORTED_MARKET_IDS:
                continue  # only markets with real, supported meaning

            for outcome in market.get("outcomes", []):
                try:
                    odds = float(outcome.get("odds", 0))
                    probability = float(outcome.get("probability", 0))
                except (TypeError, ValueError):
                    continue

                if odds < config.MIN_ODDS_PER_LEG:
                    continue

                legs.append({
                    "event_id": event_id,
                    "match_name": f"{home} vs {away}",
                    "team_id": home,  # used for correlation check
                    "league": match.get("tournamentName", ""),
                    "market_id": market_id,
                    "market_name": config.SUPPORTED_MARKET_IDS[market_id],
                    "outcome_id": str(outcome.get("id", "")),
                    "selection": outcome.get("desc", outcome.get("description", "")),
                    "odds": odds,
                    "current_probability": probability,
                    "kickoff_time": kickoff_iso,
                    "last_odds_change_time": market.get("lastOddsChangeTime"),
                })
        return legs
