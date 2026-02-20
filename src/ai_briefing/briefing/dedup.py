from typing import Iterable, Set

from ..config import Settings
from ..db import get_conn

def getRecentBriefRefIds(settings: Settings, kind: str, refIds: Iterable[int], hours: int) -> Set[int]:
    refIdList = [int(x) for x in refIds]
    if not refIdList or hours <= 0:
        return set()

    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ref_id FROM briefs WHERE kind = %s AND ref_id = ANY(%s) AND created_at > NOW() - (%s || ' hours')::interval",
                (kind, refIdList, hours),
            )
            rows = cur.fetchall()
    return {int(r[0]) for r in rows if r and r[0] is not None}
