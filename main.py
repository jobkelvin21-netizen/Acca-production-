"""
main.py - BOT A
Flask API. Bot NEVER places bets - analysis and recommendation only.
Polls SportyBet repeatedly through the day to build movement history, then
runs a daily selection cycle. Day 1 = test mode, Day 2+ = real mode,
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
from analysis_engine import AccumulatorBuilder, Verifier, DailyPickSelector, MovementChecker
from database import SportyBetScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("main_a")

app = Flask(__name__)


def poll_and_filter_legs() -> list:
    """
    One full poll cycle: pull today's matches, get detail for each, extract
    legs, run the movement check on every leg, keep only ones that pass.
    """
    matches = SportyBetScraper.get_upcoming_matches("football")
    if not matches:
        logger.warning("⚠️ No matches found this poll.")
        return []

    qualifying_legs = []
    checked = 0
    for m in matches[:40]:  # cap per poll to stay reasonable on requests
        detail = SportyBetScraper.get_event_detail(m["event_id"])
        if not detail:
            continue
        detail["tournamentName"] = m.get("tournament_name", "")
        legs = SportyBetScraper.extract_legs(detail)
        checked += 1

        for leg in legs:
            passed, increase, reasoning = MovementChecker.check_leg(leg)
            if passed:
                leg["_movement_passed"] = True
                leg["_movement_increase"] = increase
                leg["_movement_reasoning"] = reasoning
                qualifying_legs.append(leg)

    logger.info(f"✅ Poll complete: {checked} matches checked, {len(qualifying_legs)} legs "
                f"show real upward movement + sufficient probability")
    return qualifying_legs


def run_daily_cycle() -> bool:
    logger.info("Building today's #1 pick from legs with confirmed movement...")
    qualifying_legs = poll_and_filter_legs()

    if not qualifying_legs:
        logger.warning("⚠️ No legs qualify yet today (no movement history or no real movement). Cycle skipped.")
        return False

    logger.info(f"Step: Building 3-leg accas (tight {config.KICKOFF_WINDOW_HOURS}h kickoff window, no correlation)...")
    candidates = AccumulatorBuilder.build_candidates(qualifying_legs)
    if not candidates:
        logger.warning("⚠️ No valid candidate accas built (kickoff window or correlation rejected everything). Cycle skipped.")
        return False

    logger.info(f"Step: Verifying candidates ({config.MIN_VERIFICATION_SCORE}+/100, constant threshold)...")
    verified = Verifier.verify_all(candidates)
    if not verified:
        logger.warning(f"⚠️ Nothing cleared {config.MIN_VERIFICATION_SCORE}+. Cycle skipped - this is normal.")
        return False

    logger.info("Step: Selecting the single #1 pick...")
    best = DailyPickSelector.get_best_pick(verified)
    if not best:
        return False

    logger.info("Step: Saving #1 pick to Supabase (confirmed by readback)...")
    saved = db.Database.save_verified_accumulator(best)
    if saved:
        logger.info("✅ DAILY CYCLE COMPLETE - #1 pick ready for Lovable dashboard.\n")
        return True
    logger.error("❌ SUPABASE SAVE FAILED - dashboard will show nothing until this is fixed.")
    return False


def background_loop():
    """Polls repeatedly through the day to build movement history, then runs
    the selection cycle once per POLL_INTERVAL_HOURS cycle."""
    while True:
        try:
            mode_status = config.get_mode_status()
            logger.info(f"\n{'='*80}\n{config.BOT_NAME}\n{'='*80}")
            logger.info(mode_status["status"])
            if config.is_test_mode_active():
                logger.info("🧪 TEST MODE - identical logic to real mode. No real bets should be placed yet.")
            else:
                logger.info("🔴 REAL MODE - identical logic as test mode. Manual betting enabled.")

            run_daily_cycle()
        except Exception as e:
            logger.error(f"Cycle error: {e}")

        sleep_seconds = config.POLL_INTERVAL_HOURS * 3600
        logger.info(f"Sleeping {config.POLL_INTERVAL_HOURS}h until next poll...\n")
        time.sleep(sleep_seconds)


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
        "kickoff_window_hours": config.KICKOFF_WINDOW_HOURS,
        "poll_interval_hours": config.POLL_INTERVAL_HOURS,
    }), 200


@app.route("/daily-pick", methods=["GET"])
def daily_pick():
    acca = db.get_daily_top_acca()
    mode_status = config.get_mode_status()
    if acca:
        return jsonify({
            "success": True, "pick": acca, "mode": mode_status["status"],
            "message": "Today's #1 pick.",
            "instruction": "Recommendation only. Bet manually on SportyBet if you choose, then record it here."
        }), 200
    return jsonify({"success": False, "mode": mode_status["status"],
                     "message": "No pick cleared the bar yet - nothing in Supabase to show."}), 404


@app.route("/set-bankroll", methods=["POST"])
def set_bankroll():
    data = request.get_json(force=True)
    config.CURRENT_BANKROLL = float(data.get("amount", 0))
    return jsonify({"success": True, "bankroll": config.CURRENT_BANKROLL}), 200


@app.route("/place-bet", methods=["POST"])
def place_bet():
    """Records a bet the USER placed manually on SportyBet. Bot does not place bets."""
    data = request.get_json(force=True)
    try:
        dbc = db.Database.connect()
        dbc.table("user_placements_a").insert({
            "accumulator_id": data.get("acca_id"), "stake": float(data.get("stake", 0)),
            "odds_placed": float(data.get("odds_placed", 0)), "platform": "SportyBet",
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
