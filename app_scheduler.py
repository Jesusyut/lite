import os

_scheduler = None

def maybe_start_scheduler():
    """
    Start APScheduler only if RUN_SCHEDULER=true.
    This prevents multiple workers from running duplicate jobs.
    Call once at Flask app init.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if os.getenv("RUN_SCHEDULER", "false").lower() != "true":
        return None
    from warmers import start_scheduler
    _scheduler = start_scheduler()
    return _scheduler
