"""
main.py - BOT A: 15+ ODDS HUNTER
Flask API. Bot NEVER places bets - analysis and recommendation only.
Saves EXACTLY ONE pick per successful daily cycle to Supabase, confirmed
by readback. Day 1 = test mode (identical logic), Day 2+ = real mode,
auto-switches after 24h - no manual code change needed either day.
"""

import logging
import sys
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, request

import database as db
from config import config
from analysis_engine import AccumulatorBuilder, Verifier, DailyPickSelector
from database import MelbetScraper, FBRefScraper, ESPNScraper, LiquipediaScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("main_a")

app = Flask(__name__)

SPORTS = ["esports", "championship", "league_one", "cricket", "tennis", "lower_leagues"]


def gather_real_data(legs):
    lookup = {}
    for leg in legs:
        selection = leg.get("selection", "")
        if not selection or selection in lookup:
            continue
        try:
            if leg["sport"] == "esports":
                lookup[selection] = LiquipediaScraper.get_team_stats(selection)
            elif leg["sport"] == "tennis":
                lookup[selection] = ESPNScraper.get_player_form(selection)
            elif leg["sport"] in ("championship", "league_one", "lower_leagues"):
                lookup[selection] = FBRefScraper.get_team_stats(selection)
            else:
                lookup[selection] = {}
        except Exception as e:
            logger.warning(f"Real data lookup failed for {selection}: {e}")
            lookup[selection] = {}
    return lookup


def run_daily_cycle() -> bool:
    logger.info("Step 1: Scanning sloppy pre-match markets on Melbet (supported market types only)...")
    all_legs = []
    for sport in SPORTS:
        all_legs.extend(MelbetScraper.get_odds(sport))
    logger.info(f"✅ Total candidate legs: {len(all_legs)}")

    if not all_legs:
        logger.warning("⚠️ No legs found today. Cycle skipped - nothing sent to Supabase.")
        return False

    logger.info("Step 2: Building 3-leg accas (>=2.0 odds/leg, tight kickoff window, no correlation)...")
    candidates = AccumulatorBuilder.build_candidates(all_legs)
    if not candidates:
        logger.warning("⚠️ No valid candidate accas built today. Cycle skipped - nothing sent to Supabase.")
        return False

    logger.info("Step 3: Gathering real supporting data (fbref/ESPN/Liquipedia)...")
    all_selections = [leg for c in candidates for leg in c["legs"]]
    real_data_lookup = gather_real_data(all_selections)

    logger.info(f"Step 4: Verifying candidates ({config.MIN_VERIFICATION_SCORE}+/100, price-gap vs other bookmakers, constant threshold)...")
    verified = Verifier.verify_all(candidates, real_data_lookup)
    if not verified:
        logger.warning(f"⚠️ No acca cleared {config.MIN_VERIFICATION_SCORE}+ today. Cycle skipped - nothing sent to Supabase. This is normal.")
        return False

    logger.info("Step 5: Selecting the single #1 pick...")
    best = DailyPickSelector.get_best_pick(verified)
    if not best:
        logger.warning("⚠️ No pick selected. Nothing sent to Supabase.")
        return False

    logger.info("Step 6: Saving the ONE #1 pick to Supabase (confirmed by readback)...")
    saved = db.Database.save_verified_accumulator(best)
    if saved:
        logger.info("✅ DAILY CYCLE COMPLETE - exactly 1 pick sent and confirmed in Supabase. Ready for Lovable dashboard to display.\n")
        return True
    logger.error("❌ SUPABASE SAVE FAILED - pick was NOT sent. Check Supabase credentials/tables. Dashboard will show nothing until this is fixed.")
    return False


def background_loop():
    while True:
        try:
            mode_status = config.get_mode_status()
            logger.info(f"\n{'='*80}\nBOT A - 15+ ODDS HUNTER\n{'='*80}")
            logger.info(mode_status["status"])
            if config.is_test_mode_active():
                logger.info("🧪 TEST MODE - identical logic to real mode. No real bets should be placed yet.")
            else:
                logger.info("🔴 REAL MODE - identical logic as test mode. Manual betting enabled.")
            run_daily_cycle()
        except Exception as e:
            logger.error(f"Cycle error: {e}")
        time.sleep(24 * 3600)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot": config.BOT_NAME}), 200


@app.route("/status", methods=["GET"])
def status():
    mode_status = config.get_mode_status()
    return jsonify({
        "bot": config.BOT_NAME,
        "bankroll": config.CURRENT_BANKROLL,
        "recommended_stake": config.get_recommended_bet_size(),
        "mode": mode_status["status"],
        "is_test_mode": config.is_test_mode_active(),
        "verification_threshold": config.MIN_VERIFICATION_SCORE,
        "target_combined_odds": config.TARGET_COMBINED_ODDS,
        "min_odds_per_leg": config.MIN_ODDS_PER_LEG,
    }), 200


@app.route("/daily-pick", methods=["GET"])
def daily_pick():
    """This is what Lovable's dashboard should call to display today's pick."""
    acca = db.get_daily_top_acca()
    mode_status = config.get_mode_status()
    if acca:
        return jsonify({
            "success": True, "pick": acca, "mode": mode_status["status"],
            "message": "Bot A's #1 pick today.",
            "instruction": "Recommendation only. Bet manually on Melbet if you choose, then record it here."
        }), 200
    return jsonify({"success": False, "mode": mode_status["status"],
                     "message": "No pick cleared the bar today - nothing in Supabase to show."}), 404


@app.route("/set-bankroll", methods=["POST"])
def set_bankroll():
    data = request.get_json(force=True)
    config.CURRENT_BANKROLL = float(data.get("amount", 0))
    return jsonify({"success": True, "bankroll": config.CURRENT_BANKROLL}), 200


@app.route("/place-bet", methods=["POST"])
def place_bet():
    """Records a bet the USER placed manually on Melbet. Bot does not place bets."""
    data = request.get_json(force=True)
    try:
        dbc = db.Database.connect()
        dbc.table("user_placements_a").insert({
            "accumulator_id": data.get("acca_id"), "stake": float(data.get("stake", 0)),
            "odds_placed": float(data.get("odds_placed", 0)), "platform": "Melbet",
            "placed_at": datetime.now().isoformat()
        }).execute()
        config.CURRENT_BANKROLL -= float(data.get("stake", 0))
        return jsonify({"success": True, "new_bankroll": config.CURRENT_BANKROLL}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/record-result", methods=["POST"])
def record_result():
    data = request.get_json(force=True)
    try:
        dbc = db.Database.connect()
        dbc.table("verified_results_a").insert({
            "accumulator_id": data.get("acca_id"), "result": data.get("result"),
            "profit_loss": float(data.get("profit_loss", 0)), "resolved_at": datetime.now().isoformat()
        }).execute()
        config.CURRENT_BANKROLL += float(data.get("profit_loss", 0))
        return jsonify({"success": True, "new_bankroll": config.CURRENT_BANKROLL}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def main():
    if not config.validate():
        sys.exit(1)
    db.Database.connect()
    db.Database.init_tables()

    t = threading.Thread(target=background_loop, daemon=True)
    t.start()

    logger.info("✅ Bot A API running on http://127.0.0.1:8001")
    app.run(host="0.0.0.0", port=8001)


if __name__ == "__main__":
    main()
