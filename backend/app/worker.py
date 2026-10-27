"""Background worker: delivers notifications and runs the time-based follow-ups.

Each pass: send due notifications, remind people about unacknowledged alerts, report
overdue work orders, hand stale escalated conversations back, close idle ones.

    python -m app.worker            # run until stopped (Ctrl+C / SIGTERM)
    python -m app.worker --once     # one pass, for cron or a scheduled task

Several workers can run at once; rows are claimed with SKIP LOCKED.
"""

import argparse
import logging
import signal
import threading

from app.assistant.service import close_idle, sweep_escalations
from app.config import get_settings
from app.db import system_session
from app.logging_config import configure_logging
from app.notify.dispatcher import deliver_pending
from app.services.sweeps import sweep_alerts, sweep_work_orders

logger = logging.getLogger("opscore.worker")


def run_once() -> dict:
    with system_session() as session:
        reminded = sweep_alerts(session)
    with system_session() as session:
        overdue = sweep_work_orders(session)
    with system_session() as session:
        handed_back = sweep_escalations(session)
    with system_session() as session:
        closed = close_idle(session)
    # Deliver last, so reminders queued above go out in the same pass.
    stats = deliver_pending(limit=500)
    summary = {
        **stats.__dict__,
        "alert_reminders": reminded,
        "work_orders_overdue": overdue,
        "conversations_handed_back": handed_back,
        "conversations_closed": closed,
    }
    if stats.attempted or reminded or overdue or handed_back or closed:
        logger.info("worker pass", extra=summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="OpsCore background worker")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between passes")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)

    if args.once:
        run_once()
        return

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    logger.info("worker started", extra={"interval": args.interval})
    while not stop.is_set():
        try:
            run_once()
        except Exception:
            logger.exception("worker pass failed; retrying next interval")
        stop.wait(args.interval)
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
