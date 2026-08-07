import sqlite3
from typing import List, Tuple, Optional
import logging
from datetime import datetime
import pytz

# Константы
HELP_MESSAGE = """
📱 *Available commands*:

*General commands:*
/start \\- Start using the bot
/help \\- Show this help message

*Admin commands:*
/join \\- Add the current group to the driver system
/broadcast \\- Start a new broadcast \\(text, photo or video\\)
/drivers \\- View the list of driver groups
/fleet \\- Shows the location of all drivers
/location \\(truck number\\)\\- Shows the location of a specific driver by truck number
/add\\_user \\- Grant a user access
/remove\\_user \\- Revoke a user's access
/landmarks \\- View the list of landmarks
/add\\_landmark \\- Add a new landmark
/edit\\_landmark \\- Edit a landmark
/remove\\_landmark \\- Remove a landmark
/trailers \\- Active trailer assignments
/trailer \\(ID\\) \\- Trailer details
/set\\_return \\- Set a return deadline
/overdue \\- Overdue returns

*About the bot:*
This bot manages communication with drivers\\.
Works only in driver groups \\(name format: \\#NUMBER NAME\\)\\.

*Need help?*
Contact the developer: @n1dleee
"""


class Database:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.create_tables()
        logging.info("Database initialized")
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Таблица водителей
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            chat_id INTEGER PRIMARY KEY,
            truck_number TEXT NOT NULL,
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
        """)
        
        # Таблица запланированных сообщений
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_messages (
            id INTEGER PRIMARY KEY,
            message_text TEXT NOT NULL,
            schedule_time TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS approved_users (
            user_id INTEGER PRIMARY KEY
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS landmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            radius_meters REAL DEFAULT 200,
            address TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trailer_positions (
            trailer_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            speed REAL,
            raw_status TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trailer_id, provider)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trailer_position_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trailer_id TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trailer_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trailer_id TEXT NOT NULL,
            truck_number TEXT,
            driver_name TEXT,
            pick_location TEXT,
            pick_time TIMESTAMP,
            return_location TEXT,
            return_deadline TIMESTAMP,
            drop_time TIMESTAMP,
            drop_location TEXT,
            status TEXT DEFAULT 'PICKED',
            chat_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            message TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            suppressed_until TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS geofence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trailer_id TEXT NOT NULL,
            landmark_id INTEGER,
            event_type TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        self.conn.commit()
        logging.info("Database tables created/verified")

    def add_driver_chat(self, chat_id: int, truck_number: str) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO drivers (chat_id, truck_number, is_active)
                VALUES (?, ?, 1)
                """,
                (chat_id, truck_number)
            )
            self.conn.commit()
            logging.info(f"Added/Updated driver chat: {chat_id}, truck #{truck_number}")
            return True
        except sqlite3.Error as e:
            logging.error(f"Error adding driver chat: {e}")
            return False

    def get_all_drivers(self) -> List[int]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT chat_id FROM drivers WHERE is_active = 1")
            return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logging.error(f"Error getting drivers: {e}")
            return []

    def get_driver_info(self, chat_id: int) -> Optional[Tuple[str, bool]]:
        """Возвращает информацию о водителе: (truck_number, is_active)"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT truck_number, is_active FROM drivers WHERE chat_id = ?",
                (chat_id,)
            )
            return cursor.fetchone()
        except sqlite3.Error as e:
            logging.error(f"Error getting driver info: {e}")
            return None

    def add_scheduled_message(self, message_text: str, schedule_time: str) -> int:
        """Добавляет новое запланированное сообщение"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO scheduled_messages (message_text, schedule_time)
                VALUES (?, ?)
                """,
                (message_text, schedule_time)
            )
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logging.error(f"Error adding scheduled message: {e}")
            return -1

    def get_scheduled_messages(self) -> List[Tuple]:
        """Возвращает все активные запланированные сообщения"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT id, message_text, schedule_time, created_at
                FROM scheduled_messages
                WHERE is_active = 1
                ORDER BY schedule_time
                """
            )
            return cursor.fetchall()
        except sqlite3.Error as e:
            logging.error(f"Error getting scheduled messages: {e}")
            return []

    def delete_scheduled_message(self, message_id: int) -> bool:
        """Удаляет запланированное сообщение"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE scheduled_messages SET is_active = 0 WHERE id = ?",
                (message_id,)
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Error deleting scheduled message: {e}")
            return False

    def update_scheduled_message(self, message_id: int, new_text: str, new_time: str) -> bool:
        """Обновляет запланированное сообщение"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                UPDATE scheduled_messages 
                SET message_text = ?, schedule_time = ?
                WHERE id = ? AND is_active = 1
                """,
                (new_text, new_time, message_id)
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Error updating scheduled message: {e}")
            return False
        
    def add_approved_user(self, user_id: int):
        """Добавляет ID пользователя в список одобренных"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO approved_users (user_id) VALUES (?)", (user_id,))
            self.conn.commit()
            logging.info(f"Пользователь {user_id} одобрен")
        except sqlite3.Error as e:
            logging.error(f"Ошибка при добавлении одобренного пользователя: {e}")

    def is_user_approved(self, user_id: int) -> bool:
        """Проверяет, одобрен ли пользователь"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT 1 FROM approved_users WHERE user_id = ?
            """, (user_id,))
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logging.error(f"Ошибка при проверке одобрения пользователя: {e}")
            return False

    # ---- Landmarks ----

    def add_landmark(self, name: str, latitude: float, longitude: float,
                     radius_meters: float = 200, address: str = None,
                     created_by: int = None) -> int:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """INSERT INTO landmarks (name, latitude, longitude, radius_meters, address, created_by)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, latitude, longitude, radius_meters, address, created_by),
            )
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logging.error(f"Error adding landmark: {e}")
            return -1

    def get_landmarks(self) -> List[Tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, name, latitude, longitude, radius_meters, address, created_by, created_at "
                "FROM landmarks WHERE is_active = 1"
            )
            return cursor.fetchall()
        except sqlite3.Error as e:
            logging.error(f"Error getting landmarks: {e}")
            return []

    def get_landmark_by_id(self, landmark_id: int) -> Optional[Tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, name, latitude, longitude, radius_meters, address "
                "FROM landmarks WHERE id = ? AND is_active = 1",
                (landmark_id,),
            )
            return cursor.fetchone()
        except sqlite3.Error as e:
            logging.error(f"Error getting landmark: {e}")
            return None

    def update_landmark(self, landmark_id: int, **kwargs) -> bool:
        allowed = {"name", "latitude", "longitude", "radius_meters", "address"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return False
        try:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [landmark_id]
            cursor = self.conn.cursor()
            cursor.execute(
                f"UPDATE landmarks SET {set_clause} WHERE id = ? AND is_active = 1",
                values,
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error updating landmark: {e}")
            return False

    def deactivate_landmark(self, landmark_id: int) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE landmarks SET is_active = 0 WHERE id = ?",
                (landmark_id,),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error deactivating landmark: {e}")
            return False

    # ---- Trailer Positions ----

    def upsert_trailer_position(self, trailer_id: str, provider: str,
                                latitude: float, longitude: float,
                                speed: float = None, raw_status: str = None) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """INSERT INTO trailer_positions (trailer_id, provider, latitude, longitude, speed, raw_status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(trailer_id, provider)
                   DO UPDATE SET latitude=excluded.latitude, longitude=excluded.longitude,
                                 speed=excluded.speed, raw_status=excluded.raw_status,
                                 updated_at=CURRENT_TIMESTAMP""",
                (trailer_id, provider, latitude, longitude, speed, raw_status),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Error upserting trailer position: {e}")
            return False

    def get_trailer_positions(self, provider: str = None) -> List[Tuple]:
        try:
            cursor = self.conn.cursor()
            if provider:
                cursor.execute(
                    "SELECT trailer_id, provider, latitude, longitude, speed, raw_status, updated_at "
                    "FROM trailer_positions WHERE provider = ?",
                    (provider,),
                )
            else:
                cursor.execute(
                    "SELECT trailer_id, provider, latitude, longitude, speed, raw_status, updated_at "
                    "FROM trailer_positions"
                )
            return cursor.fetchall()
        except sqlite3.Error as e:
            logging.error(f"Error getting trailer positions: {e}")
            return []

    def get_trailer_position(self, trailer_id: str) -> Optional[Tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT trailer_id, provider, latitude, longitude, speed, raw_status, updated_at "
                "FROM trailer_positions WHERE UPPER(trailer_id) = UPPER(?)",
                (trailer_id,),
            )
            return cursor.fetchone()
        except sqlite3.Error as e:
            logging.error(f"Error getting trailer position: {e}")
            return None

    # ---- Position History ----

    def add_position_history(self, trailer_id: str, latitude: float, longitude: float) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO trailer_position_history (trailer_id, latitude, longitude) VALUES (?, ?, ?)",
                (trailer_id, latitude, longitude),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Error adding position history: {e}")
            return False

    def get_position_history_window(self, trailer_id: str, minutes: int = 30) -> List[Tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT latitude, longitude, recorded_at FROM trailer_position_history "
                "WHERE trailer_id = ? AND recorded_at >= datetime('now', ?)"
                " ORDER BY recorded_at ASC",
                (trailer_id, f"-{minutes} minutes"),
            )
            return cursor.fetchall()
        except sqlite3.Error as e:
            logging.error(f"Error getting position history: {e}")
            return []

    def cleanup_old_positions(self, hours: int = 2) -> int:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "DELETE FROM trailer_position_history WHERE recorded_at < datetime('now', ?)",
                (f"-{hours} hours",),
            )
            self.conn.commit()
            return cursor.rowcount
        except sqlite3.Error as e:
            logging.error(f"Error cleaning up positions: {e}")
            return 0

    # ---- Trailer Assignments ----

    def create_assignment(self, trailer_id: str, truck_number: str = None,
                          driver_name: str = None, pick_location: str = None,
                          chat_id: int = None) -> int:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """INSERT INTO trailer_assignments
                   (trailer_id, truck_number, driver_name, pick_location, pick_time, status, chat_id)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'PICKED', ?)""",
                (trailer_id, truck_number, driver_name, pick_location, chat_id),
            )
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logging.error(f"Error creating assignment: {e}")
            return -1

    def get_active_assignment(self, trailer_id: str) -> Optional[Tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, trailer_id, truck_number, driver_name, pick_location, pick_time, "
                "return_location, return_deadline, drop_time, drop_location, status, chat_id, created_at "
                "FROM trailer_assignments "
                "WHERE UPPER(trailer_id) = UPPER(?) AND status NOT IN ('RETURNED') "
                "ORDER BY created_at DESC LIMIT 1",
                (trailer_id,),
            )
            return cursor.fetchone()
        except sqlite3.Error as e:
            logging.error(f"Error getting active assignment: {e}")
            return None

    def get_active_assignments(self) -> List[Tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, trailer_id, truck_number, driver_name, pick_location, pick_time, "
                "return_location, return_deadline, drop_time, drop_location, status, chat_id, created_at "
                "FROM trailer_assignments WHERE status NOT IN ('RETURNED') ORDER BY created_at DESC"
            )
            return cursor.fetchall()
        except sqlite3.Error as e:
            logging.error(f"Error getting active assignments: {e}")
            return []

    def update_assignment_status(self, assignment_id: int, status: str, **kwargs) -> bool:
        try:
            updates = {"status": status}
            allowed_extra = {"drop_time", "drop_location", "return_location", "return_deadline"}
            for k, v in kwargs.items():
                if k in allowed_extra:
                    updates[k] = v
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [assignment_id]
            cursor = self.conn.cursor()
            cursor.execute(
                f"UPDATE trailer_assignments SET {set_clause} WHERE id = ?",
                values,
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error updating assignment: {e}")
            return False

    def set_return_deadline(self, assignment_id: int, return_deadline: str,
                            return_location: str = None) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE trailer_assignments SET return_deadline = ?, return_location = ? WHERE id = ?",
                (return_deadline, return_location, assignment_id),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error setting return deadline: {e}")
            return False

    def get_overdue_assignments(self) -> List[Tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, trailer_id, truck_number, driver_name, pick_location, pick_time, "
                "return_location, return_deadline, drop_time, drop_location, status, chat_id, created_at "
                "FROM trailer_assignments "
                "WHERE return_deadline IS NOT NULL AND return_deadline < datetime('now') "
                "AND status NOT IN ('RETURNED') "
                "ORDER BY return_deadline ASC"
            )
            return cursor.fetchall()
        except sqlite3.Error as e:
            logging.error(f"Error getting overdue assignments: {e}")
            return []

    # ---- Alerts Log ----

    def log_alert(self, alert_type: str, entity_id: str, message: str,
                  suppressed_until: str = None) -> int:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """INSERT INTO alerts_log (alert_type, entity_id, message, suppressed_until)
                   VALUES (?, ?, ?, ?)""",
                (alert_type, entity_id, message, suppressed_until),
            )
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logging.error(f"Error logging alert: {e}")
            return -1

    def is_alert_suppressed(self, alert_type: str, entity_id: str) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT 1 FROM alerts_log "
                "WHERE alert_type = ? AND entity_id = ? "
                "AND suppressed_until IS NOT NULL AND suppressed_until > datetime('now') "
                "ORDER BY sent_at DESC LIMIT 1",
                (alert_type, entity_id),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logging.error(f"Error checking alert suppression: {e}")
            return False

    def clear_alert_suppression(self, alert_type: str, entity_id: str) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE alerts_log SET suppressed_until = NULL "
                "WHERE alert_type = ? AND entity_id = ? AND suppressed_until IS NOT NULL",
                (alert_type, entity_id),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Error clearing suppression: {e}")
            return False

    # ---- Geofence Events ----

    def add_geofence_event(self, trailer_id: str, landmark_id: int,
                           event_type: str, latitude: float, longitude: float) -> int:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """INSERT INTO geofence_events (trailer_id, landmark_id, event_type, latitude, longitude)
                   VALUES (?, ?, ?, ?, ?)""",
                (trailer_id, landmark_id, event_type, latitude, longitude),
            )
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logging.error(f"Error adding geofence event: {e}")
            return -1

    def get_last_geofence_event(self, trailer_id: str, landmark_id: int) -> Optional[Tuple]:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, trailer_id, landmark_id, event_type, latitude, longitude, recorded_at "
                "FROM geofence_events "
                "WHERE trailer_id = ? AND landmark_id = ? "
                "ORDER BY recorded_at DESC LIMIT 1",
                (trailer_id, landmark_id),
            )
            return cursor.fetchone()
        except sqlite3.Error as e:
            logging.error(f"Error getting last geofence event: {e}")
            return None


def format_scheduled_messages(messages: List[Tuple]) -> str:
    """Форматирует список запланированных сообщений для вывода"""
    if not messages:
        return "📝 No active scheduled messages"

    result = "📅 *Scheduled messages:*\n\n"
    for msg_id, text, time, created_at in messages:
        result += f"*ID:* {msg_id}\n"
        result += f"*Send time:* {time}\n"
        result += f"*Created:* {created_at}\n"
        result += f"*Text:*\n{text[:100]}{'...' if len(text) > 100 else ''}\n\n"
    return result

def is_driver_group(chat_title: str) -> bool:
    """Проверяет, соответствует ли название чата формату группы водителя"""
    if not chat_title:
        return False
    parts = chat_title.split()
    return len(parts) >= 2 and parts[0].startswith('#') and parts[0][1:].isdigit()

def get_truck_number(chat_title: str) -> Optional[str]:
    """Извлекает номер грузовика из названия чата"""
    if not is_driver_group(chat_title):
        return None
    return chat_title.split()[0][1:]
