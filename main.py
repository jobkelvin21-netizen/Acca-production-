"""
main.py - BOT #1 ORCHESTRATOR
Daily cycle: generate 50 accas, show top 1 per day
"""

import logging
import sys
import time
import threading
from datetime import datetime
from flask import Flask, jsonify, request
from config import config
import database as db
from analysis_engine import (
    EdgeCalculator, AccumulatorBuilder, Verifier, DailyAccaSelector
)

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("bot_v1")

# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    """Health check for Uptime Robot"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "bankroll": config.CURRENT_BANKROLL,
        "phase": "PHASE_1_BOOTSTRAP"
    }), 200

@app.route("/status", methods=["GET"])
def status():
    """Bot status"""
    return jsonify({
        "bankroll": config.CURRENT_BANKROLL,
        "phase": "PHASE_1_BOOTSTRAP",
        "target": 10_000_000,
        "recommended_stake": config.get_recommended_bet_size(),
        "phase_1_complete": config.is_phase_1_complete()
    }), 200

@app.route("/daily-acca", methods=["GET"])
def get_daily_acca():
    """Get today's top acca"""
    try:
        acca = db.get_daily_top_acca()
        
        if acca:
            return jsonify({
                "success": True,
                "acca": acca
            }), 200
        else:
            return jsonify({
                "success": False,
                "message": "No acca generated yet for today"
            }), 404
    
    except Exception as e:
        logger.error(f"Get daily acca error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/set-bankroll", methods=["POST"])
def set_bankroll():
    """Set custom bankroll"""
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "error": "No data"}), 400
        
        try:
            amount = float(data.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid amount"}), 400
        
        if amount <= 0:
            return jsonify({"success": False, "error": "Must be > 0"}), 400
        
        if config.set_starting_bankroll(amount):
            return jsonify({
                "success": True,
                "bankroll": amount
            }), 200
        else:
            return jsonify({"success": False}), 400
    
    except Exception as e:
        logger.error(f"Set bankroll error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/place-bet", methods=["POST"])
def place_bet():
    """Record bet placement"""
    try:
        data = request.json
        
        try:
            stake = float(data.get("stake", 0))
            odds_placed = float(data.get("odds_placed", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid stake/odds"}), 400
        
        acca_id = data.get("accumulator_id")
        
        if stake <= 0:
            return jsonify({"error": "Stake must be > 0"}), 400
        
        if stake > config.CURRENT_BANKROLL:
            return jsonify({
                "error": f"Stake exceeds bankroll"
            }), 400
        
        if db.record_placement(acca_id, stake, odds_placed):
            new_balance = config.CURRENT_BANKROLL - stake
            db.update_bankroll(new_balance)
            
            return jsonify({
                "success": True,
                "message": f"Bet recorded: ₦{stake:,.0f} @ {odds_placed:.2f}",
                "new_bankroll": new_balance
            }), 200
        else:
            return jsonify({"success": False}), 500
    
    except Exception as e:
        logger.error(f"Place bet error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/record-result", methods=["POST"])
def record_result():
    """Record accumulator result"""
    try:
        data = request.json
        
        acca_id = data.get("accumulator_id")
        result = data.get("result")  # "won" or "lost"
        profit_loss = float(data.get("profit_loss", 0))
        
        if db.record_result(acca_id, result, profit_loss):
            new_balance = config.CURRENT_BANKROLL + profit_loss
            db.update_bankroll(new_balance)
            
            status = "✅ PHASE_1_COMPLETE" if config.is_phase_1_complete() else "PHASE_1_BOOTSTRAP"
            
            return jsonify({
                "success": True,
                "message": f"Result: {result}",
                "new_bankroll": new_balance,
                "status": status
            }), 200
        else:
            return jsonify({"success": False}), 500
    
    except Exception as e:
        logger.error(f"Record result error: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# BOT LOGIC
# ============================================================================

class BotV1:
    """Bot orchestrator"""
    
    @staticmethod
    def run_daily_cycle():
        """Run daily bot cycle: generate 50 accas, show top 1"""
        try:
            logger.info(f"\n{'='*80}")
            logger.info(f"BOT #1 DAILY CYCLE")
            logger.info(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
            logger.info(f"Bankroll: ₦{config.CURRENT_BANKROLL:,.0f}")
            logger.info(f"Phase: PHASE_1_BOOTSTRAP")
            logger.info(f"Target: ₦10,000,000")
            logger.info(f"{'='*80}\n")
            
            # ================================================================
            # STEP 1: SCAN REAL MARKETS
            # ================================================================
            logger.info("Step 1: Scanning sloppy markets...")
            
            all_legs = []
            
            # Scan each sloppy market type
            sloppy_sports = ["esports", "championship", "league_one", "cricket", "tennis"]
            
            for sport in sloppy_sports:
                legs = db.MelbetScraper.get_odds(sport)
                all_legs.extend(legs)
                logger.info(f"  └─ {sport}: {len(legs)} legs found")
            
            logger.info(f"✅ Total: {len(all_legs)} candidate legs\n")
            
            if not all_legs:
                logger.warning("No legs found")
                return False
            
            # ================================================================
            # STEP 2: CALCULATE REAL EDGE
            # ================================================================
            logger.info("Step 2: Calculating real edge...")
            
            analyzed_legs = []
            
            for leg in all_legs[:100]:  # Sample top 100
                edge = EdgeCalculator.calculate_edge(leg)
                
                if edge >= config.MIN_EDGE_PER_LEG:
                    leg["edge"] = edge
                    analyzed_legs.append(leg)
            
            logger.info(f"✅ {len(analyzed_legs)} legs with {config.MIN_EDGE_PER_LEG:.0%}+ edge\n")
            
            if len(analyzed_legs) < 3:
                logger.warning("Not enough quality legs")
                return False
            
            # ================================================================
            # STEP 3: BUILD ACCUMULATORS
            # ================================================================
            logger.info("Step 3: Building 3-leg accumulators...")
            
            built_accas = AccumulatorBuilder.build_accumulators(analyzed_legs)
            
            logger.info(f"✅ Built {len(built_accas)} accumulators\n")
            
            if not built_accas:
                logger.warning("No accumulators built")
                return False
            
            # ================================================================
            # STEP 4: VERIFY WITH 5-CHECK SYSTEM
            # ================================================================
            logger.info("Step 4: Running 5-check verification...")
            
            verified_accas = Verifier.verify_accumulators(built_accas)
            
            logger.info(f"✅ {len(verified_accas)} accumulators verified (80+/100)\n")
            
            if not verified_accas:
                logger.warning("No verified accumulators")
                return False
            
            # ================================================================
            # STEP 5: CALCULATE RECOMMENDED STAKE
            # ================================================================
            logger.info("Step 5: Calculating stakes...")
            
            for acca in verified_accas:
                acca["recommended_stake"] = config.get_recommended_bet_size()
            
            logger.info(f"✅ Recommended stake per acca: ₦{config.get_recommended_bet_size():,.0f}\n")
            
            # ================================================================
            # STEP 6: SAVE TO DATABASE
            # ================================================================
            logger.info("Step 6: Saving to database...")
            
            saved_count = 0
            for acca in verified_accas:
                if db.save_verified_accumulator(acca):
                    saved_count += 1
            
            logger.info(f"✅ Saved {saved_count} accumulators\n")
            
            # ================================================================
            # STEP 7: SELECT TOP ACCA FOR DAY
            # ================================================================
            logger.info("Step 7: Selecting top acca...")
            
            top_acca = DailyAccaSelector.get_top_acca(verified_accas)
            
            if top_acca:
                logger.info("✅ Top acca selected and ready for betting\n")
                return True
            else:
                logger.warning("No top acca selected")
                return False
        
        except Exception as e:
            logger.error(f"❌ Daily cycle error: {e}", exc_info=True)
            return False

def flask_thread():
    """Run Flask in background"""
    logger.info(f"🌐 Starting bot #1 on port {config.PORT}")
    app.run(host="0.0.0.0", port=config.PORT, debug=False, use_reloader=False)

def main():
    """Main bot entry point"""
    logger.info("\n" + "="*80)
    logger.info("BOT #1 - ACCUMULATOR LAUNCHER")
    logger.info("15+ odds, sloppy markets only, 8 days to 10M+")
    logger.info("="*80 + "\n")
    
    # Validate config
    if not config.validate():
        sys.exit(1)
    
    # Initialize database
    db.Database.connect()
    db.Database.init_tables()
    
    # Set bot start time
    if config.BOT_START_TIME is None:
        config.BOT_START_TIME = datetime.now()
        logger.info(f"✅ Bot started: {config.BOT_START_TIME.isoformat()}\n")
    
    # Set default bankroll if not set
    if config.STARTING_BANKROLL == 0:
        config.set_starting_bankroll(1000)
        logger.info(f"⚠️ Using default bankroll: ₦1,000\n")
    
    # Start Flask in background
    flask_thread_obj = threading.Thread(target=flask_thread, daemon=True)
    flask_thread_obj.start()
    
    logger.info("✅ API Endpoints:")
    logger.info(f"   GET  /health (Uptime Robot)")
    logger.info(f"   GET  /status")
    logger.info(f"   GET  /daily-acca (Today's top pick)")
    logger.info(f"   POST /set-bankroll")
    logger.info(f"   POST /place-bet")
    logger.info(f"   POST /record-result\n")
    
    # Main loop: Run daily cycle
    logger.info("🤖 Starting daily bot cycle...\n")
    
    cycle = 0
    while True:
        try:
            cycle += 1
            BotV1.run_daily_cycle()
            
            # Wait 24 hours until next cycle
            logger.info("\n⏰ Waiting 24 hours until next cycle...\n")
            time.sleep(86400)  # 24 hours
        
        except KeyboardInterrupt:
            logger.info("\n✅ Bot stopped by user")
            break
        
        except Exception as e:
            logger.error(f"❌ Main loop error: {e}", exc_info=True)
            time.sleep(10)

if __name__ == "__main__":
    main()
