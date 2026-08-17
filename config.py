"""
config.py - BOT A: SportyBet direct scraping, odds-movement + probability strategy
No API keys except Supabase. Direct scraping against confirmed real SportyBet
endpoints (verified via live network inspection, not guessed).
"""

import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_NAME = "BOT A - SPORTYBET ODDS-MOVEMENT HUNTER"

    # === SUPABASE (ONLY credentials needed) ===
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    # === SPORTYBET DIRECT ENDPOINTS (confirmed real via network inspection) ===
    SPORTYBET_BASE = "https://www.sportybet.com/api/ng/factsCenter"
    SPORTYBET_LIST_URL = f"{SPORTYBET_BASE}/pcUpcomingEvents"
    SPORTYBET_EVENT_URL = f"{SPORTYBET_BASE}/event"

    # Confirmed sport IDs (football verified live; others added as confirmed)
    SPORT_IDS = {
        "football": "sr:sport:1",
    }

    # Market IDs confirmed from real football list call
    FOOTBALL_MARKET_IDS = "1,18,10,29,11,26,36,14,60100"

    # === ACCUMULATOR STRUCTURE ===
    LEGS_PER_ACCA = 3
    MIN_ODDS_PER_LEG = 2.0
    TARGET_COMBINED_ODDS = 15.0   # hoped-for target, not a hard floor
    MAX_COMBINED_ODDS = None      # no cap - real verified picks above 15 still used

    # === VERIFICATION (CONSTANT - Day 1 = Day 2+, never switches) ===
    MIN_VERIFICATION_SCORE = 90

    # === ODDS-MOVEMENT SIGNAL (replaces invented probability formula) ===
    MIN_CURRENT_PROBABILITY = 0.45     # leg must be MORE LIKELY THAN NOT (tightened from 0.35)
    MIN_PROBABILITY_INCREASE = 0.08    # must have risen at least 8 points (tightened from 0.05)
    MIN_SNAPSHOT_GAP_HOURS = 4.0       # tightened from 3.0 - more time = more confidence
    MIN_SNAPSHOT_COUNT = 3             # NEW: need at least 3 readings, not just first+last
    POLL_INTERVAL_HOURS = 1.5

    # === MARKET RULES ===
    KICKOFF_WINDOW_HOURS = 2.0         # HARD RULE: all 3 legs must kick off within this window
    MIN_MINUTES_BEFORE_KICKOFF = 15
    ALLOW_CORRELATED_LEGS = False

    # Only markets SportyBet actually attaches outcomes+probability to that we use.
    # market_id values confirmed from real event detail response.
    SUPPORTED_MARKET_IDS = {
        "1": "1X2 (match winner)",
        "18": "Over/Under Goals",
        "10": "Double Chance",
        "29": "Handicap",
        "60100": "Both Teams To Score",
    }

    # === SLOPPY MARKETS: exclude the most heavily-bet, most efficient leagues ===
    EXCLUDED_LEAGUES = {
        "premier league", "champions league", "la liga", "bundesliga",
        "serie a", "ligue 1", "world cup", "euro", "european championship",
        "uefa nations league", "copa america",
    }

    # === STAKING ===
    PHASE_1_BET_FRACTION = 0.50
    STARTING_BANKROLL = 500.0
    CURRENT_BANKROLL = 500.0

    # === NO STREAK, NO COUNTDOWN, NO FIXED TARGET ===
    # 6 straight wins is the hope, spread over however long it takes.

    # === DEPLOYMENT / TEST-MODE AUTO-SWITCH (unchanged mechanism) ===
    DEPLOYMENT_TIMESTAMP_FILE = "bot_a_deployment.log"
    TEST_MODE_DURATION_HOURS = 24

    @staticmethod
    def record_deployment_time():
        try:
            if not os.path.exists(Config.DEPLOYMENT_TIMESTAMP_FILE):
                t = datetime.now()
                with open(Config.DEPLOYMENT_TIMESTAMP_FILE, "w") as f:
                    f.write(t.isoformat())
                return t
            with open(Config.DEPLOYMENT_TIMESTAMP_FILE, "r") as f:
                return datetime.fromisoformat(f.read().strip())
        except Exception:
            return datetime.now()

    @staticmethod
    def is_test_mode_active():
        try:
            if os.path.exists(Config.DEPLOYMENT_TIMESTAMP_FILE):
                with open(Config.DEPLOYMENT_TIMESTAMP_FILE, "r") as f:
                    deployment_time = datetime.fromisoformat(f.read().strip())
            else:
                deployment_time = Config.record_deployment_time()
            hours_elapsed = (datetime.now() - deployment_time).total_seconds() / 3600
            return hours_elapsed < Config.TEST_MODE_DURATION_HOURS
        except Exception:
            return True

    @staticmethod
    def get_mode_status():
        try:
            if os.path.exists(Config.DEPLOYMENT_TIMESTAMP_FILE):
                with open(Config.DEPLOYMENT_TIMESTAMP_FILE, "r") as f:
                    deployment_time = datetime.fromisoformat(f.read().strip())
            else:
                deployment_time = Config.record_deployment_time()
            hours_elapsed = (datetime.now() - deployment_time).total_seconds() / 3600
            if hours_elapsed < Config.TEST_MODE_DURATION_HOURS:
                remaining = Config.TEST_MODE_DURATION_HOURS - hours_elapsed
                return {"mode": "TEST", "deployed": deployment_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "hours_elapsed": round(hours_elapsed, 1), "hours_remaining": round(remaining, 1),
                        "status": f"🧪 TEST MODE ({round(remaining,1)}h remaining) - same logic as real mode, no real bets"}
            return {"mode": "REAL", "deployed": deployment_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "hours_elapsed": round(hours_elapsed, 1), "hours_remaining": 0,
                    "status": f"🔴 REAL BETTING ACTIVE ({round(hours_elapsed,1)}h since deployment)"}
        except Exception:
            return {"mode": "TEST", "status": "🧪 TEST MODE (default)"}

    @staticmethod
    def get_recommended_bet_size():
        return round(Config.CURRENT_BANKROLL * Config.PHASE_1_BET_FRACTION, 2)

    @staticmethod
    def validate():
        ok = True
        if not Config.SUPABASE_URL:
            print("❌ Missing SUPABASE_URL")
            ok = False
        if not Config.SUPABASE_SERVICE_ROLE_KEY:
            print("❌ Missing SUPABASE_SERVICE_ROLE_KEY")
            ok = False
        if ok:
            print("✅ Config validated: Supabase credentials present (no other API keys used)")
        return ok


config = Config()
