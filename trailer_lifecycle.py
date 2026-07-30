import logging
from datetime import datetime
from typing import Optional

from function import Database

logger = logging.getLogger(__name__)


def create_assignment(db: Database, trailer_id: str, truck_number: str = None,
                      driver_name: str = None, pick_location: str = None,
                      chat_id: int = None) -> int:
    existing = db.get_active_assignment(trailer_id)
    if existing:
        db.update_assignment_status(existing[0], "RETURNED",
                                    drop_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("Auto-closed previous assignment %d for trailer %s", existing[0], trailer_id)

    assignment_id = db.create_assignment(
        trailer_id=trailer_id,
        truck_number=truck_number,
        driver_name=driver_name,
        pick_location=pick_location,
        chat_id=chat_id,
    )
    logger.info("Created assignment %d for trailer %s", assignment_id, trailer_id)
    return assignment_id


def complete_assignment(db: Database, trailer_id: str,
                        drop_location: str = None) -> bool:
    assignment = db.get_active_assignment(trailer_id)
    if not assignment:
        logger.warning("No active assignment for trailer %s on #drop", trailer_id)
        return False

    return db.update_assignment_status(
        assignment[0], "RETURNED",
        drop_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        drop_location=drop_location,
    )


def set_return_deadline(db: Database, assignment_id: int,
                        return_deadline: str, return_location: str = None) -> bool:
    return db.set_return_deadline(assignment_id, return_deadline, return_location)


def get_overdue_returns(db: Database) -> list:
    return db.get_overdue_assignments()
