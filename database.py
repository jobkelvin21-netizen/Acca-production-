"""
database.py - BOT A
Real scrapers (Melbet + comparison bookmakers for price gap, fbref/ESPN/Liquipedia
for raw stats) + Supabase storage. No API keys other than Supabase.

IMPORTANT: save_verified_accumulator() below is the ONLY place that writes a pick
to Supabase, and it is only ever called ONCE per day, with the single #1 pick -
never with the full candidate list. This is deliberate and logged clearly so it's
verifiable from the terminal output that only one row goes in per day.
"""

import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
from supabase import create_client, Client
from config import config

logger = logging.getLogger("database_a")


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
        logger.info("✅ Assuming tables exist: verified_accumulators_a, user_placements_a, verified_results_a, pick_log_a")

    @staticmethod
    def save_verified_accumulator(acca: Dict) -> bool:
        """
        Saves the SINGLE #1 pick of the day. Called exactly once per successful
        daily cycle - never for the full candidate pool. Confirms the write by
        reading the row back immediately after insert.
        """
        try:
            dbc = Database.connect()
            payload = {
                "id": acca["id"],
                "legs": acca["legs"],
                "combined_odds": acca["combined_odds"],
                "verification_score": acca["verification_score"],
                "signal_strength": acca.get("signal_strength"),
                "reasoning": acca.get("reasoning"),
                "recommended_stake": acca.get("recommended_stake"),
                "status": "pending",
                "created_at": datetime.now().isoformat(),
            }
            insert_result = dbc.table("verified_accumulators_a").insert(payload).execute()

            if not insert_result.data:
                logger.error("❌ SUPABASE WRITE FAILED - insert returned no data")
                return False

            # Confirm the row actually exists by reading it back
            confirm = dbc.table("verified_accumulators_a").select("id").eq("id", acca["id"]).execute()
            if confirm.data and len(confirm.data) > 0:
                logger.info(f"✅ CONFIRMED IN SUPABASE: pick {acca['id']} is saved and readable (verified_accumulators_a)")
                # Also log to pick_log_a for the outcome-tracking history
                try:
                    dbc.table("pick_log_a").insert({
                        "accumulator_id": acca["id"],
                        "reasoning": acca.get("reasoning"),
                        "combined_odds": acca["combined_odds"],
                        "verification_score": acca["verification_score"],
                        "created_at": datetime.now().isoformat(),
                    }).execute()
                except Exception as e:
                    logger.warning(f"Pick log write failed (non-critical): {e}")
                return True
            else:
                logger.error(f"❌ SUPABASE WRITE UNVERIFIED - row {acca['id']} not found on readback")
                return False

        except Exception as e:
            logger.error(f"❌ SUPABASE SAVE ERROR: {e}")
            return False


def get_daily_top_acca() -> Optional[Dict]:
    """Fetch today's #1 pick - there should only ever be one pending row at a time."""
    try:
        dbc = Database.connect()
        result = dbc.table("verified_accumulators_a").select("*").eq(
            "status", "pending"
        ).order("created_at", desc=True).limit(1).execute()
        acca = result.data[0] if result.data else None
        if acca:
            logger.info(f"✅ Retrieved pending pick from Supabase: {acca.get('id')}")
        else:
            logger.warning("⚠️ No pending pick found in Supabase.")
        return acca
    except Exception as e:
        logger.error(f"Get #1 acca error: {e}")
        return None


# ============================================================================
# REAL SCRAPERS
# ============================================================================

class MelbetScraper:
    """Scrape REAL pre-match odds from Melbet.ng"""

    @staticmethod
    def get_odds(sport: str) -> List[Dict]:
        try:
            logger.info(f"Scanning Melbet.ng for {sport} (pre-match only)...")
            url = f"https://www.melbet.ng/en/popular/Sports/?sports={sport}"
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.content, "html.parser")

            odds_list = []
            for market in soup.find_all("div", class_="market-item")[:30]:
                try:
                    market_type = market.get("data-market-type", "match_winner")
                    if market_type not in config.SUPPORTED_MARKET_TYPES:
                        continue  # skip markets with no real data backing

                    league = market.get("data-league", "unknown")
                    selection = market.get("data-selection", "unknown")
                    odds = float(market.get("data-odds", "0"))
                    status = market.get("data-status", "prematch")
                    start_time_str = market.get("data-start-time")

                    if status.lower() != "prematch":
                        continue
                    if not start_time_str:
                        continue

                    match_start = datetime.fromisoformat(start_time_str)
                    minutes_to_kickoff = (match_start - datetime.now()).total_seconds() / 60
                    if minutes_to_kickoff < config.MIN_MINUTES_BEFORE_KICKOFF:
                        continue
                    if odds < config.MIN_ODDS_PER_LEG:
                        continue

                    odds_list.append({
                        "sport": sport, "league": league, "market_type": market_type,
                        "selection": selection, "team_id": market.get("data-team-id", selection),
                        "odds": odds, "bookmaker": "melbet",
                        "match_id": market.get("data-match-id", f"{league}-{selection}"),
                        "market_name": f"{league} - {selection} ({market_type})",
                        "kickoff_time": start_time_str,
                        "is_quick_finish": market_type in ("first_half_winner", "map_winner", "set_winner"),
                        "scanned_at": datetime.now().isoformat(),
                    })
                except Exception:
                    continue

            logger.info(f"✅ Melbet {sport}: {len(odds_list)} candidates (supported markets, ≥{config.MIN_ODDS_PER_LEG} odds)")
            return odds_list
        except Exception as e:
            logger.warning(f"Melbet scrape error ({sport}): {e}")
            return []


class ComparisonOddsScraper:
    """Scrape the SAME matches from other bookmakers, purely for price comparison.
    No account or API key needed - public odds pages only."""

    @staticmethod
    def get_comparison_odds(match_id: str, selection: str) -> List[float]:
        prices = []
        for book in config.COMPARISON_BOOKMAKERS:
            try:
                url = f"https://www.{book}.com/match/{match_id}"
                response = requests.get(url, timeout=8)
                soup = BeautifulSoup(response.content, "html.parser")
                el = soup.find("span", {"data-selection": selection})
                if el:
                    prices.append(float(el.text.strip()))
            except Exception:
                continue
        return prices

    @staticmethod
    def get_price_gap(melbet_odds: float, match_id: str, selection: str) -> float:
        """Returns how much better Melbet's price is vs the other-book consensus.
        0.0 if no comparison data available or no meaningful gap."""
        others = ComparisonOddsScraper.get_comparison_odds(match_id, selection)
        if not others:
            return 0.0
        consensus = sum(others) / len(others)
        if consensus <= 0:
            return 0.0
        gap = (melbet_odds - consensus) / consensus
        return gap


class FBRefScraper:
    """Scrape REAL football stats (xG, goals) from fbref.com"""

    @staticmethod
    def get_team_stats(team_name: str) -> Dict:
        try:
            search_url = f"https://fbref.com/en/search/search.php?search={team_name}"
            response = requests.get(search_url, timeout=10)
            soup = BeautifulSoup(response.content, "html.parser")
            team_link = soup.find("a", href=lambda x: x and "/squads/" in x)
            if not team_link:
                return {}
            team_response = requests.get(f"https://fbref.com{team_link['href']}", timeout=10)
            team_soup = BeautifulSoup(team_response.content, "html.parser")
            table = team_soup.find("table", {"id": "stats_squads"})
            if not table:
                return {}
            xg, goals, games = 0.0, 0.0, 0
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) > 7:
                    try:
                        xg_val = float(cells[7].text.strip())
                        goals_val = float(cells[1].text.strip())
                        games_val = int(cells[0].text.strip())
                        if games_val > 0:
                            xg, goals, games = xg_val / games_val, goals_val / games_val, games_val
                    except (ValueError, IndexError):
                        continue
            return {"team": team_name, "xg_per_match": round(xg, 2), "goals_per_match": round(goals, 2),
                    "games_analyzed": games, "form_summary": f"{round(goals,2)} goals/game, {round(xg,2)} xG/game",
                    "data_source": "fbref.com"}
        except Exception as e:
            logger.warning(f"fbref scrape error: {e}")
            return {}


class ESPNScraper:
    """Scrape REAL H2H and form data from ESPN"""

    @staticmethod
    def get_h2h_record(player1: str, player2: str) -> Dict:
        try:
            search_url = f"https://www.espn.com/search?query={player1}+vs+{player2}"
            response = requests.get(search_url, timeout=10)
            soup = BeautifulSoup(response.content, "html.parser")
            h2h = soup.find("div", class_="h2h-record")
            if h2h and "-" in h2h.text:
                p1, p2 = h2h.text.split("-")[:2]
                p1_wins, p2_wins = int(p1.strip()), int(p2.strip())
                return {"player1": player1, "player2": player2,
                        "form_summary": f"H2H {p1_wins}-{p2_wins}", "data_source": "espn.com"}
            return {"player1": player1, "player2": player2, "form_summary": "H2H unavailable"}
        except Exception as e:
            logger.warning(f"ESPN H2H scrape error: {e}")
            return {}

    @staticmethod
    def get_player_form(player_name: str) -> Dict:
        try:
            search_url = f"https://www.espn.com/search?query={player_name}"
            response = requests.get(search_url, timeout=10)
            soup = BeautifulSoup(response.content, "html.parser")
            results = soup.find("div", class_="recent-results")
            if results:
                form = "".join("W" if "W" in r.text.upper() else "L"
                                for r in results.find_all("span", class_="result")[:5])
                return {"player": player_name, "form_summary": f"Last 5: {form}", "data_source": "espn.com"}
            return {"player": player_name, "form_summary": "form unavailable"}
        except Exception as e:
            logger.warning(f"ESPN form scrape error: {e}")
            return {}


class LiquipediaScraper:
    """Scrape REAL esports data from Liquipedia"""

    @staticmethod
    def get_team_stats(team_name: str, game: str = "dota2") -> Dict:
        try:
            url = f"https://liquipedia.net/{game}/{team_name}"
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.content, "html.parser")
            stats = soup.find("div", class_="team-stats")
            if stats:
                winrate_el = stats.find("span", class_="winrate")
                winrate = winrate_el.text.strip() if winrate_el else "unavailable"
                return {"team": team_name, "game": game, "form_summary": f"Winrate: {winrate}",
                        "data_source": "liquipedia.net"}
            return {"team": team_name, "game": game, "form_summary": "stats unavailable"}
        except Exception as e:
            logger.warning(f"Liquipedia scrape error: {e}")
            return {}
