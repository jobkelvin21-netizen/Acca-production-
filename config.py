"""
config.py - BOT A: 15+ ODDS HUNTER (multi-platform price comparison + raw data)
"""

import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()  # Reads .env file and loads SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY into environment

class Config:
    BOT_NAME = "BOT A - 15+ ODDS HUNTER"

    # === SUPABASE (ONLY credentials needed) ===
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    # === ACCUMULATOR STRUCTURE ===
    LEGS_PER_ACCA = 3
    MIN_ODDS_PER_LEG = 2.0
    TARGET_COMBINED_ODDS = 15.0   # what the bot is hunting for
    MIN_COMBINED_ODDS = None      # no hard floor - best verified pick shown regardless
    MAX_COMBINED_ODDS = None      # no cap - if it finds 18, 22+, still verify and use it

    # === VERIFICATION (CONSTANT - same Day 1 and Day 2+, never switches) ===
    MIN_VERIFICATION_SCORE = 90
    MIN_PRICE_GAP_PERCENT = 0.05  # Melbet must be 5%+ better than other-book consensus to count

    # === MARKET RULES ===
    SLOPPY_MARKETS_ONLY = True
    QUICK_FINISH_PREFERENCE = True
    KICKOFF_WINDOW_HOURS = 2
    MIN_MINUTES_BEFORE_KICKOFF = 15
    ALLOW_CORRELATED_LEGS = False

    # Only markets with a REAL free data source behind them. Nothing else is used -
    # corners, cards, first-to-score, throw-ins etc. have no honest data source
    # available, so they are never included, not guessed.
    SUPPORTED_MARKET_TYPES = {
        "match_winner":      "form + xG overperformance (fbref/ESPN/Liquipedia)",
        "first_half_winner": "form + xG overperformance (quick-finish market)",
        "handicap":          "form + xG overperformance (adjusted for handicap line)",
        "over_under_goals":  "goals-per-match average (fbref)",
        "map_winner":        "esports winrate + recent form (Liquipedia)",
        "set_winner":        "H2H + player form (ESPN, tennis)",
    }

    # Other bookmakers scraped purely for price comparison (no account/API key needed,
    # public odds pages only)
    COMPARISON_BOOKMAKERS = ["bet9ja", "sportybet", "1xbet"]

    # === STAKING ===
    PHASE_1_BET_FRACTION = 0.50
    STARTING_BANKROLL = 500.0
    CURRENT_BANKROLL = 500.0

    # === NO STREAK, NO COUNTDOWN, NO FIXED TARGET ===

    # === DEPLOYMENT / TEST-MODE AUTO-SWITCH (unchanged mechanism) ===
    DEPLOYMENT_TIMESTAMP_FILE = "bot_a_deployment.log"
    TEST_MODE_DURATION_HOURS = 24  # Day 1 = test (same logic), Day 2+ = real, auto-switch

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
