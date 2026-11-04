import os
from dataclasses import dataclass, field
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

@dataclass
class ServiceItem:
    service_id: str
    title: str
    description: str
    price_inr: float
    delivery_content: str  # URL, invite link, instructions, or credentials delivered upon approval

@dataclass
class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_GROUP_ID: int = int(os.getenv("ADMIN_GROUP_ID", "0"))
    ADMIN_IDS: List[int] = field(default_factory=lambda: [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "6934393623").split(",") if x.strip().isdigit()
    ])
    UPI_ID: str = os.getenv("UPI_ID", "merchant@upi")
    UPI_NAME: str = os.getenv("UPI_NAME", "Store Merchant")
    QR_IMAGE_PATH: str = os.getenv("QR_IMAGE_PATH", "assets/qr_code.png")
    DB_PATH: str = os.getenv("DB_PATH", "payment_bot.db")

    # Initial services to seed if database is fresh
    DEFAULT_SERVICES: List[ServiceItem] = field(default_factory=lambda: [
        ServiceItem(
            service_id="vip_access",
            title="💎 VIP Telegram Channel (1 Month)",
            description="Access to private premium signals, alerts, and priority discussion.",
            price_inr=199.0,
            delivery_content="🎉 Here is your one-time invite link to the VIP Channel:\n👉 https://t.me/+SampleVIPInviteLink123\n\nThank you for your purchase!"
        ),
        ServiceItem(
            service_id="course_bundle",
            title="📚 Masterclass E-Book & Guide",
            description="Comprehensive guide and materials in PDF format with lifetime updates.",
            price_inr=349.0,
            delivery_content="🎉 Download your Masterclass materials here:\n👉 https://drive.google.com/sample_course_link\n\nPassword: VIP_MEMBER_2026"
        ),
        ServiceItem(
            service_id="custom_setup",
            title="⚡ 1-on-1 Consultation / Setup Support",
            description="Direct 45-minute remote setup assistance and consultation session.",
            price_inr=799.0,
            delivery_content="🎉 Your consultation order is confirmed!\nPlease message our support manager @AdminSupport with your Order ID to schedule your call."
        ),
    ])

config = Config()
