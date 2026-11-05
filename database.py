import aiosqlite
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, AsyncGenerator
from config import config

logger = logging.getLogger(__name__)

@asynccontextmanager
async def get_connection() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Provides a managed aiosqlite connection that automatically closes on exit."""
    conn = await aiosqlite.connect(config.DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        await conn.close()

async def init_db() -> None:
    """Initialize database tables and seed default services if table is empty."""
    async with get_connection() as conn:
        await conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS services (
            service_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            price_inr REAL NOT NULL,
            delivery_content TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            service_id TEXT NOT NULL,
            amount REAL NOT NULL,
            utr TEXT UNIQUE,
            screenshot_file_id TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING_PAYMENT',
            admin_id INTEGER,
            rejection_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(service_id) REFERENCES services(service_id)
        );

        CREATE INDEX IF NOT EXISTS idx_orders_utr ON orders(utr);
        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS order_messages (
            message_id INTEGER,
            chat_id INTEGER,
            order_id TEXT,
            PRIMARY KEY(message_id, chat_id)
        );
        """)

        # Add receipt_msg_id column to orders if not already present
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN receipt_msg_id INTEGER")
        except Exception:
            pass

        # Add last_bot_msg_id column to users if not already present
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN last_bot_msg_id INTEGER")
        except Exception:
            pass

        # Seed initial payment settings if not present
        default_settings = {
            "upi_id": config.UPI_ID,
            "upi_name": config.UPI_NAME,
            "qr_image_path": config.QR_IMAGE_PATH
        }
        for k, v in default_settings.items():
            await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))

        # Check if services table is empty; if so, populate with default services
        async with conn.execute("SELECT COUNT(*) as count FROM services") as cursor:
            row = await cursor.fetchone()
            if row and row["count"] == 0:
                for s in config.DEFAULT_SERVICES:
                    await conn.execute(
                        """
                        INSERT INTO services (service_id, title, description, price_inr, delivery_content, is_active)
                        VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (s.service_id, s.title, s.description, s.price_inr, s.delivery_content)
                    )
                logger.info(f"Seeded {len(config.DEFAULT_SERVICES)} default services into database.")

        await conn.commit()

async def upsert_user(user_id: int, username: Optional[str], full_name: Optional[str]) -> None:
    async with get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name
            """,
            (user_id, username or "", full_name or "")
        )
        await conn.commit()

async def get_services(active_only: bool = True) -> List[Dict[str, Any]]:
    async with get_connection() as conn:
        query = "SELECT * FROM services"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY price_inr ASC"
        async with conn.execute(query) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_service(service_id: str) -> Optional[Dict[str, Any]]:
    async with get_connection() as conn:
        async with conn.execute("SELECT * FROM services WHERE service_id = ?", (service_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def create_order(
    order_id: str,
    user_id: int,
    service_id: str,
    amount: float,
    username: Optional[str] = None,
    full_name: Optional[str] = None
) -> None:
    async with get_connection() as conn:
        # Ensure user exists in users table to satisfy FOREIGN KEY constraint
        await conn.execute(
            """
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = COALESCE(NULLIF(excluded.username, ''), users.username),
                full_name = COALESCE(NULLIF(excluded.full_name, ''), users.full_name)
            """,
            (user_id, username or "", full_name or "")
        )
        await conn.execute(
            """
            INSERT INTO orders (order_id, user_id, service_id, amount, status)
            VALUES (?, ?, ?, ?, 'PENDING_PAYMENT')
            """,
            (order_id, user_id, service_id, amount)
        )
        await conn.commit()

async def get_order(order_id: str) -> Optional[Dict[str, Any]]:
    async with get_connection() as conn:
        async with conn.execute(
            """
            SELECT o.*, s.title as service_title, s.delivery_content, u.username, u.full_name
            FROM orders o
            JOIN services s ON o.service_id = s.service_id
            JOIN users u ON o.user_id = u.user_id
            WHERE o.order_id = ?
            """,
            (order_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def check_utr_exists(utr: str) -> bool:
    """Return True if UTR already exists in any order (prevents duplicate receipt fraud)."""
    cleaned_utr = utr.strip()
    async with get_connection() as conn:
        async with conn.execute(
            "SELECT 1 FROM orders WHERE utr = ? AND status IN ('PENDING_VERIFICATION', 'COMPLETED')",
            (cleaned_utr,)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

async def submit_order_proof(order_id: str, screenshot_file_id: str, utr: Optional[str] = None) -> bool:
    """
    Attach screenshot (and optional UTR) to order, transition status to PENDING_VERIFICATION.
    """
    cleaned_utr = utr.strip() if utr else None
    async with get_connection() as conn:
        try:
            await conn.execute(
                """
                UPDATE orders
                SET utr = ?,
                    screenshot_file_id = ?,
                    status = 'PENDING_VERIFICATION',
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
                """,
                (cleaned_utr, screenshot_file_id, order_id)
            )
            await conn.commit()
            return True
        except aiosqlite.IntegrityError:
            # If UTR has a collision (e.g. duplicate test receipt), still save proof & screenshot!
            await conn.execute(
                """
                UPDATE orders
                SET screenshot_file_id = ?,
                    status = 'PENDING_VERIFICATION',
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
                """,
                (screenshot_file_id, order_id)
            )
            await conn.commit()
            return True

async def save_admin_order_message(message_id: int, chat_id: int, order_id: str) -> None:
    """Map an admin verification card message to its order ID for reply-to-deliver."""
    async with get_connection() as conn:
        await conn.execute(
            """
            INSERT OR REPLACE INTO order_messages (message_id, chat_id, order_id)
            VALUES (?, ?, ?)
            """,
            (message_id, chat_id, order_id)
        )
        await conn.commit()

async def get_order_by_message(message_id: int, chat_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve the order associated with an admin card message."""
    async with get_connection() as conn:
        async with conn.execute(
            "SELECT order_id FROM order_messages WHERE message_id = ? AND chat_id = ?",
            (message_id, chat_id)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return await get_order(row["order_id"])
            return None

async def save_order_receipt_msg(order_id: str, message_id: int) -> None:
    """Store customer's temporary receipt message ID for auto-cleanup upon delivery."""
    async with get_connection() as conn:
        await conn.execute("UPDATE orders SET receipt_msg_id = ? WHERE order_id = ?", (message_id, order_id))
        await conn.commit()

async def set_user_last_bot_msg(user_id: int, message_id: int) -> None:
    """Track the most recent bot menu / checkout message in user's chat for spotless cleanup."""
    async with get_connection() as conn:
        await conn.execute("UPDATE users SET last_bot_msg_id = ? WHERE user_id = ?", (message_id, user_id))
        await conn.commit()

async def get_user_last_bot_msg(user_id: int) -> Optional[int]:
    """Retrieve the most recent bot menu / checkout message in user's chat."""
    async with get_connection() as conn:
        async with conn.execute("SELECT last_bot_msg_id FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return row["last_bot_msg_id"]
            return None

async def get_admin_order_messages(order_id: str) -> List[Dict[str, int]]:
    """Get all admin card messages (message_id, chat_id) across groups & DMs for an order."""
    async with get_connection() as conn:
        async with conn.execute(
            "SELECT message_id, chat_id FROM order_messages WHERE order_id = ?",
            (order_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def delete_admin_order_messages(order_id: str) -> None:
    """Clear order message records after deletion."""
    async with get_connection() as conn:
        await conn.execute("DELETE FROM order_messages WHERE order_id = ?", (order_id,))
        await conn.commit()

async def approve_order(order_id: str, admin_id: int) -> Optional[Dict[str, Any]]:
    """Marks order as COMPLETED and returns order info with delivery content."""
    async with get_connection() as conn:
        await conn.execute(
            """
            UPDATE orders
            SET status = 'COMPLETED',
                admin_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE order_id = ?
            """,
            (admin_id, order_id)
        )
        await conn.commit()
    return await get_order(order_id)

async def reject_order(order_id: str, admin_id: int, reason: str) -> Optional[Dict[str, Any]]:
    """Marks order as REJECTED with specific reason."""
    async with get_connection() as conn:
        await conn.execute(
            """
            UPDATE orders
            SET status = 'REJECTED',
                admin_id = ?,
                rejection_reason = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE order_id = ?
            """,
            (admin_id, reason, order_id)
        )
        await conn.commit()
    return await get_order(order_id)

async def get_user_orders(user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    async with get_connection() as conn:
        async with conn.execute(
            """
            SELECT o.*, s.title as service_title
            FROM orders o
            JOIN services s ON o.service_id = s.service_id
            WHERE o.user_id = ?
            ORDER BY o.created_at DESC
            LIMIT ?
            """,
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_all_users() -> List[int]:
    """Fetch all registered user IDs for broadcasting."""
    async with get_connection() as conn:
        async with conn.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [r["user_id"] for r in rows]

async def add_service(service_id: str, title: str, description: str, price_inr: float, delivery_content: str) -> bool:
    """Create a new service in the catalog."""
    async with get_connection() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO services (service_id, title, description, price_inr, delivery_content, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (service_id.strip(), title.strip(), description.strip(), float(price_inr), delivery_content.strip())
            )
            await conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def update_service_price(service_id: str, new_price: float) -> bool:
    """Update pricing for an existing service."""
    async with get_connection() as conn:
        cursor = await conn.execute(
            "UPDATE services SET price_inr = ? WHERE service_id = ?",
            (float(new_price), service_id)
        )
        await conn.commit()
        return cursor.rowcount > 0

async def update_service_delivery(service_id: str, new_content: str) -> bool:
    """Update delivery link/instructions for an existing service."""
    async with get_connection() as conn:
        cursor = await conn.execute(
            "UPDATE services SET delivery_content = ? WHERE service_id = ?",
            (new_content.strip(), service_id)
        )
        await conn.commit()
        return cursor.rowcount > 0

async def update_service_title(service_id: str, new_title: str) -> bool:
    """Update title for an existing service."""
    async with get_connection() as conn:
        cursor = await conn.execute(
            "UPDATE services SET title = ? WHERE service_id = ?",
            (new_title.strip(), service_id)
        )
        await conn.commit()
        return cursor.rowcount > 0

async def toggle_service_status(service_id: str) -> Optional[int]:
    """Toggle is_active between 1 and 0. Returns the new status (0 or 1) or None."""
    async with get_connection() as conn:
        async with conn.execute("SELECT is_active FROM services WHERE service_id = ?", (service_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            new_status = 0 if row["is_active"] == 1 else 1

        await conn.execute(
            "UPDATE services SET is_active = ? WHERE service_id = ?",
            (new_status, service_id)
        )
        await conn.commit()
        return new_status

async def delete_service(service_id: str) -> bool:
    """Soft-delete or delete a service if no completed orders depend on it, otherwise deactivate."""
    async with get_connection() as conn:
        # Check if there are orders referencing this service
        async with conn.execute("SELECT COUNT(*) as count FROM orders WHERE service_id = ?", (service_id,)) as cur:
            count = (await cur.fetchone())["count"]
            if count > 0:
                # Soft-delete to preserve order history
                await conn.execute("UPDATE services SET is_active = 0 WHERE service_id = ?", (service_id,))
                await conn.commit()
                return True

        cursor = await conn.execute("DELETE FROM services WHERE service_id = ?", (service_id,))
        await conn.commit()
        return cursor.rowcount > 0

async def get_setting(key: str, default: Optional[str] = None) -> str:
    """Retrieve dynamic setting value (e.g. upi_id, upi_name, qr_image_path)."""
    async with get_connection() as conn:
        async with conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            if row and row["value"]:
                return row["value"]
            return default or ""

async def set_setting(key: str, value: str) -> None:
    """Insert or update dynamic setting value."""
    async with get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value))
        )
        await conn.commit()


