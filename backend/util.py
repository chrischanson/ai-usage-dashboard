from datetime import datetime, timezone


def parse_iso_seconds(t_str):
    """Calculate remaining seconds from an ISO timestamp string."""
    if not t_str:
        return 0
    try:
        t_str = t_str.rstrip('Z')
        dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = (dt - now).total_seconds()
        return max(0, int(diff))
    except Exception:
        return 0
