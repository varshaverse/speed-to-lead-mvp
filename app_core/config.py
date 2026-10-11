import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application configuration for Speed-to-Lead Automation."""

    # 1. LLM Configuration (OpenAI Structured Outputs)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

    # 2. Storage Provider Configuration (Supabase or Google Sheets or local SQLite fallback)
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").strip()
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    # Optional Google Sheets Webhook (e.g. Google Apps Script Web App / Make / Zapier)
    GOOGLE_SHEETS_WEBHOOK_URL: str = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()

    # 3. Notification Dispatcher (Slack, Discord, Email via Resend/SMTP, or Twilio SMS)
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    ALERT_EMAIL_TO: str = os.getenv("ALERT_EMAIL_TO", "").strip()
    SMTP_HOST: str = os.getenv("SMTP_HOST", "").strip()
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "").strip()
    SMTP_PASS: str = os.getenv("SMTP_PASS", "").strip()
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    TWILIO_FROM_PHONE: str = os.getenv("TWILIO_FROM_PHONE", "").strip()
    TWILIO_TO_PHONE: str = os.getenv("TWILIO_TO_PHONE", "").strip()

    # 4. Security & Webhook Secret
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "").strip()
    FB_VERIFY_TOKEN: str = os.getenv("FB_VERIFY_TOKEN", "").strip() or os.getenv("WEBHOOK_SECRET", "").strip() or "speed-to-lead-token"
    FB_APP_SECRET: str = os.getenv("FB_APP_SECRET", "").strip()

    # 5. SLA Target
    TARGET_SLA_SECONDS: int = int(os.getenv("TARGET_SLA_SECONDS", "60"))
    SQLITE_PATH: str = os.getenv("SQLITE_PATH", "leads.db")

    @property
    def is_openai_configured(self) -> bool:
        return bool(self.OPENAI_API_KEY and len(self.OPENAI_API_KEY) > 10 and not self.OPENAI_API_KEY.startswith("your_"))

    @property
    def is_supabase_configured(self) -> bool:
        return bool(
            self.SUPABASE_URL
            and self.SUPABASE_SERVICE_ROLE_KEY
            and "YOUR_PROJECT" not in self.SUPABASE_URL
            and "your-service-role-key" not in self.SUPABASE_SERVICE_ROLE_KEY
        )

    @property
    def is_google_sheets_configured(self) -> bool:
        return bool(self.GOOGLE_SHEETS_WEBHOOK_URL and self.GOOGLE_SHEETS_WEBHOOK_URL.startswith("http"))

    @property
    def is_slack_configured(self) -> bool:
        return bool(
            self.SLACK_WEBHOOK_URL
            and "REPLACE/ME" not in self.SLACK_WEBHOOK_URL
            and self.SLACK_WEBHOOK_URL.startswith("https://hooks.slack.com/")
        )

    @property
    def is_discord_configured(self) -> bool:
        return bool(
            self.DISCORD_WEBHOOK_URL
            and self.DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/")
        )

    @property
    def is_email_configured(self) -> bool:
        return bool(self.ALERT_EMAIL_TO and self.SMTP_HOST and self.SMTP_USER)

    @property
    def is_sms_configured(self) -> bool:
        return bool(
            self.TWILIO_ACCOUNT_SID
            and self.TWILIO_AUTH_TOKEN
            and self.TWILIO_FROM_PHONE
            and self.TWILIO_TO_PHONE
        )


settings = Settings()
