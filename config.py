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
    
    # === 6-DAY CHALLENGE ===
    CHALLENGE_DAYS = 6  # 6 straight wins target
    CHALLENGE_MODE = True  # Track challenge progress
    
    # === BETTING RULES (PHASE 1 ONLY) ===
    PHASE_1_BET_FRACTION = 0.50  # 50% per bet (UNTIL 10M)
    
    # === BOT MODE & DAY TRACKING (AUTOMATIC 24-HOUR SWITCH) ===
    DEPLOYMENT_TIMESTAMP_FILE = "bot_deployment.log"  # Tracks EXACT deployment time
    AUTO_SWITCH_AFTER_HOURS = 24  # Auto-switch from TEST to REAL after exactly 24 hours
    
    @staticmethod
    def record_deployment_time():
        """Record exact bot deployment timestamp on FIRST startup"""
        try:
            if not os.path.exists(Config.DEPLOYMENT_TIMESTAMP_FILE):
                deployment_time = datetime.now()
                with open(Config.DEPLOYMENT_TIMESTAMP_FILE, 'w') as f:
                    f.write(deployment_time.isoformat())
                return deployment_time
            else:
                with open(Config.DEPLOYMENT_TIMESTAMP_FILE, 'r') as f:
                    return datetime.fromisoformat(f.read().strip())
        except Exception as e:
            return datetime.now()
    
    @staticmethod
    def is_test_mode_active():
        """
        AUTO-DETERMINE if TEST MODE should be active.
        
        LOGIC:
        - First 24 hours after deployment = TEST MODE (no real bets)
        - After 24 hours = REAL BETTING MODE (real bets)
        - NO MANUAL INTERVENTION NEEDED
        - FOOLPROOF: Can't forget to switch
        """
        try:
            # Get deployment time
            if os.path.exists(Config.DEPLOYMENT_TIMESTAMP_FILE):
                with open(Config.DEPLOYMENT_TIMESTAMP_FILE, 'r') as f:
                    deployment_time = datetime.fromisoformat(f.read().strip())
            else:
                # First run: Set deployment time
                deployment_time = Config.record_deployment_time()
            
            # Calculate hours elapsed since deployment
            now = datetime.now()
            hours_elapsed = (now - deployment_time).total_seconds() / 3600
            
            # TEST MODE runs for exactly 24 hours
            if hours_elapsed < 24:
                hours_remaining = 24 - hours_elapsed
                return True  # Still in TEST MODE
            else:
                # After 24 hours: AUTO-SWITCH to REAL BETTING
                return False  # REAL BETTING MODE
        
        except Exception:
            # Default to TEST MODE if any error
            return True
    
    @staticmethod
    def get_mode_status():
        """Get detailed mode status for logging"""
        try:
            if os.path.exists(Config.DEPLOYMENT_TIMESTAMP_FILE):
                with open(Config.DEPLOYMENT_TIMESTAMP_FILE, 'r') as f:
                    deployment_time = datetime.fromisoformat(f.read().strip())
                
                now = datetime.now()
                hours_elapsed = (now - deployment_time).total_seconds() / 3600
                
                if hours_elapsed < 24:
                    hours_remaining = 24 - hours_elapsed
                    return {
                        "mode": "TEST",
                        "deployed": deployment_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "hours_elapsed": round(hours_elapsed, 1),
                        "hours_remaining": round(hours_remaining, 1),
                        "status": f"🧪 TEST MODE ({round(hours_remaining, 1)}h remaining)"
                    }
                else:
                    return {
                        "mode": "REAL",
                        "deployed": deployment_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "hours_elapsed": round(hours_elapsed, 1),
                        "hours_remaining": 0,
                        "status": f"🔴 REAL BETTING ACTIVE ({round(hours_elapsed, 1)}h since deployment)"
                    }
            else:
                return {
                    "mode": "TEST",
                    "deployed": "Not yet",
                    "hours_elapsed": 0,
                    "hours_remaining": 24,
                    "status": "🧪 TEST MODE (First run)"
                }
        except Exception:
            return {
                "mode": "TEST",
                "status": "🧪 TEST MODE (Default)"
            }
    
    # === ACCUMULATOR RULES (LOCKED) ===
    MIN_LEGS_PER_ACCA = 3
    MAX_LEGS_PER_ACCA = 3
    MIN_COMBINED_ODDS = 15.0  # 15+ odds ONLY
    MAX_COMBINED_ODDS = 150.0
    
    # === VERIFICATION RULES - 90+ ONLY (ULTRA-TIGHT) ===
    MIN_VERIFICATION_SCORE = 90  # 90+/100 ONLY (ultra-tight, best accas)
    BACKUP_VERIFICATION_SCORE = 85  # Fallback if <2 at 90 (rare)
    MIN_CONFIDENCE_PER_LEG = 0.75  # 75%+ confidence only (higher threshold)
    MIN_EDGE_PER_LEG = 0.15  # 15%+ edge minimum (only real exploitable edge)
    
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
