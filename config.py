"""
config.py - BOT #1 CONFIGURATION
15+ odds, sloppy markets only, Phase 1 bootstrap to 10M
"""

import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Complete production configuration"""
    
    # === ENVIRONMENT ===
    ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
    DEBUG = False
    PORT = int(os.getenv("PORT", 8000))
    
    # === CRITICAL: ONLY 2 API KEYS NEEDED ===
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    
    # === BANKROLL MANAGEMENT ===
    STARTING_BANKROLL = 0  # Will be set by user input
    CURRENT_BANKROLL = 0  # Tracks current amount
    PHASE_1_TARGET = 10_000_000  # 10M target
    
    # === BETTING RULES (PHASE 1 ONLY) ===
    PHASE_1_BET_FRACTION = 0.50  # 50% per bet (UNTIL 10M)
    
    # === ACCUMULATOR RULES (LOCKED) ===
    MIN_LEGS_PER_ACCA = 3
    MAX_LEGS_PER_ACCA = 3
    MIN_COMBINED_ODDS = 15.0  # 15+ odds ONLY (not 22)
    MAX_COMBINED_ODDS = 150.0
    
    # === VERIFICATION RULES ===
    MIN_VERIFICATION_SCORE = 80  # 80+/100 minimum (strict)
    MIN_CONFIDENCE_PER_LEG = 0.65
    MIN_EDGE_PER_LEG = 0.08  # 8%+ edge minimum
    
    # === SLOPPY MARKETS ONLY ===
    SLOPPY_MARKETS = [
        "esports",
        "championship",
        "league_one",
        "league_two",
        "lower_leagues",
        "tennis_props",
        "cricket_overs",
        "cricket_props",
        "basketball_props",
        "handball",
        "volleyball",
        "rugby_league",
        "darts",
        "snooker",
        "table_tennis",
        "badminton"
    ]
    
    # === SHARP MARKETS TO REJECT ===
    SHARP_MARKETS = [
        "premier_league",
        "la_liga",
        "serie_a",
        "bundesliga",
        "champions_league",
        "nba",
        "nfl",
        "mlb",
        "top_10_tennis"
    ]
    
    # === TIMING ===
    ODDS_SCAN_INTERVAL = 600  # 10 minutes
    DAILY_REPORT_TIME = "09:00"  # Show top acca at 9 AM
    
    # === LOGGING ===
    LOG_FILE = "/tmp/bot_v1.log"
    LOG_LEVEL = "INFO"
    
    # === BOT START TIME ===
    BOT_START_TIME = None
    
    @staticmethod
    def validate():
        """Validate critical configuration"""
        if not Config.SUPABASE_URL:
            print("❌ FATAL: SUPABASE_URL missing")
            return False
        if not Config.SUPABASE_SERVICE_ROLE_KEY:
            print("❌ FATAL: SUPABASE_SERVICE_ROLE_KEY missing")
            return False
        
        print("✅ Config validated: Supabase credentials present")
        return True
    
    @staticmethod
    def set_starting_bankroll(amount):
        """Set custom starting bankroll"""
        if amount <= 0:
            print(f"❌ Invalid bankroll: {amount}")
            return False
        
        Config.STARTING_BANKROLL = amount
        Config.CURRENT_BANKROLL = amount
        print(f"✅ Starting bankroll set: ₦{amount:,.0f}")
        return True
    
    @staticmethod
    def update_current_bankroll(new_amount):
        """Update current bankroll"""
        Config.CURRENT_BANKROLL = new_amount
        return Config.CURRENT_BANKROLL
    
    @staticmethod
    def get_recommended_bet_size():
        """Calculate recommended stake (50% Phase 1)"""
        return Config.CURRENT_BANKROLL * Config.PHASE_1_BET_FRACTION
    
    @staticmethod
    def is_phase_1_complete():
        """Check if reached 10M"""
        return Config.CURRENT_BANKROLL >= Config.PHASE_1_TARGET

config = Config()
