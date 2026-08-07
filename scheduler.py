import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from function import Database
from providers.registry import ProviderRegistry
from geofence import check_geofence_events
from alerts import send_alert
from idle_detector import detect_idle_trailers, check_movement_reset
from theft_detector import is_trailer_with_our_driver

logger = logging.getLogger(__name__)

MOVING_SPEED_THRESHOLD = 5.0


async def poll_trailer_positions(db: Database, registry: ProviderRegistry):
    try:
        positions = await registry.get_all_positions()
        for pos in positions:
            db.upsert_trailer_position(
                trailer_id=pos.trailer_id,
                provider=pos.provider_name or "unknown",
                latitude=pos.latitude,
                longitude=pos.longitude,
                speed=pos.speed,
                raw_status=pos.raw_status,
            )
            db.add_position_history(pos.trailer_id, pos.latitude, pos.longitude)
        logger.info("Polled %d trailer positions", len(positions))
    except Exception as e:
        logger.exception("Error polling trailer positions: %s", e)


async def run_geofence_check(bot: Bot, db: Database):
    try:
        positions = db.get_trailer_positions()
        landmarks = db.get_landmarks()
        if not positions or not landmarks:
            return

        events = check_geofence_events(positions, landmarks, db)
        for ev in events:
            if ev.event_type == "arrival":
                if not ev.has_assignment:
                    msg = (
                        f"*Unknown trailer at landmark!*\n\n"
                        f"Trailer: `{ev.trailer_id}`\n"
                        f"Landmark: {ev.landmark_name}\n"
                        f"Coordinates: {ev.latitude}, {ev.longitude}\n"
                        f"[Google Maps](https://www.google.com/maps?q={ev.latitude},{ev.longitude})"
                    )
                    await send_alert(bot, db, "unassigned_at_landmark", ev.trailer_id, msg)
                else:
                    msg = (
                        f"*Trailer arrived at landmark*\n\n"
                        f"Trailer: `{ev.trailer_id}`\n"
                        f"Landmark: {ev.landmark_name}\n"
                        f"Coordinates: {ev.latitude}, {ev.longitude}"
                    )
                    await send_alert(bot, db, "geofence_arrival", ev.trailer_id, msg)

            elif ev.event_type == "departure":
                msg = (
                    f"*Trailer left landmark*\n\n"
                    f"Trailer: `{ev.trailer_id}`\n"
                    f"Landmark: {ev.landmark_name}\n"
                    f"Coordinates: {ev.latitude}, {ev.longitude}"
                )
                await send_alert(bot, db, "geofence_departure", ev.trailer_id, msg)

    except Exception as e:
        logger.exception("Geofence check error: %s", e)


async def run_theft_check(bot: Bot, db: Database):
    try:
        positions = db.get_trailer_positions()
        if not positions:
            return

        checked = 0
        for pos in positions:
            trailer_id, _provider, lat, lon, speed, raw_status, _updated = pos
            if lat is None or lon is None:
                continue

            is_moving = False
            if speed is not None and speed > MOVING_SPEED_THRESHOLD:
                is_moving = True
            elif raw_status and "MOVING" in raw_status.upper():
                is_moving = True

            if not is_moving:
                continue

            checked += 1
            with_driver, nearest_truck, distance = await is_trailer_with_our_driver(lat, lon)

            if with_driver:
                continue

            if nearest_truck:
                detail = f"Nearest truck: #{nearest_truck} ({distance / 1000:.1f} km)"
            else:
                detail = "No ELD trucks found"

            msg = (
                f"*THEFT RISK: Trailer moving without our driver!*\n\n"
                f"Trailer: `{trailer_id}`\n"
                f"Speed: {speed}\n"
                f"Coordinates: {lat}, {lon}\n"
                f"{detail}\n"
                f"[Google Maps](https://www.google.com/maps?q={lat},{lon})"
            )
            await send_alert(bot, db, "theft_risk", trailer_id, msg)

        logger.info("Theft check: %d moving trailers checked", checked)
    except Exception as e:
        logger.exception("Theft check error: %s", e)


async def check_overdue_returns(bot: Bot, db: Database):
    try:
        overdue = db.get_overdue_assignments()
        for assignment in overdue:
            a_id, trailer_id, truck, driver, _, _, ret_loc, ret_deadline, _, _, status, _, _ = assignment
            msg = (
                f"*Trailer return overdue!*\n\n"
                f"Trailer: `{trailer_id}`\n"
                f"Truck: #{truck}\n"
                f"Driver: {driver}\n"
                f"Deadline: {ret_deadline}\n"
                f"Return to: {ret_loc or 'not specified'}"
            )
            await send_alert(bot, db, "overdue_return", trailer_id, msg)
    except Exception as e:
        logger.exception("Overdue returns check error: %s", e)


async def run_idle_check(bot: Bot, db: Database):
    try:
        results = detect_idle_trailers(db)
        for r in results:
            if not r.is_idle:
                if check_movement_reset(db, r.trailer_id):
                    db.clear_alert_suppression("idle_30min", r.trailer_id)
                continue

            msg = (
                f"*Trailer idle for 30+ min!*\n\n"
                f"Trailer: `{r.trailer_id}`\n"
                f"Max displacement: {r.max_displacement_m:.0f}m\n"
                f"GPS points: {r.num_points}\n"
                f"Coordinates: {r.latest_lat}, {r.latest_lon}\n"
                f"[Google Maps](https://www.google.com/maps?q={r.latest_lat},{r.latest_lon})"
            )
            await send_alert(bot, db, "idle_30min", r.trailer_id, msg)
    except Exception as e:
        logger.exception("Idle check error: %s", e)


async def cleanup_position_history(db: Database):
    try:
        deleted = db.cleanup_old_positions(hours=3)
        if deleted > 0:
            logger.info("Cleaned up %d old position records", deleted)
    except Exception as e:
        logger.exception("Cleanup error: %s", e)


def setup_scheduler(bot: Bot, db: Database, registry: ProviderRegistry) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        poll_trailer_positions, "interval", minutes=30,
        args=[db, registry], id="poll_trailer_positions",
    )
    scheduler.add_job(
        run_geofence_check, "interval", minutes=10,
        args=[bot, db], id="check_geofences",
    )
    scheduler.add_job(
        check_overdue_returns, "interval", minutes=30,
        args=[bot, db], id="check_overdue_returns",
    )
    scheduler.add_job(
        run_idle_check, "interval", minutes=10,
        args=[bot, db], id="check_idle",
    )
    scheduler.add_job(
        run_theft_check, "interval", hours=2,
        args=[bot, db], id="check_theft",
    )
    scheduler.add_job(
        cleanup_position_history, "interval", hours=2,
        args=[db], id="cleanup_positions",
    )

    scheduler.start()
    logger.info(
        "Scheduler started: poll=30min, geofence=10min, idle=10min, "
        "overdue=30min, theft=2h, cleanup=2h"
    )
    return scheduler
