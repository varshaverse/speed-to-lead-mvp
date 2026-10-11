# Speed-to-Lead (Blaze AI CFO)

Blaze's Facebook leads waited a median of **22 hours** for a first call. This app cuts that to **a few seconds**.

When a lead arrives, it is saved, scored by an LLM (fit score 1-5, a one-line reason, intent, and a drafted personalized reply), sent to me on Discord, and appended to a Google Sheet. The whole path is timed from webhook received to message delivered, and the dashboard shows that number against the 60-second target.

```
Facebook lead-ad payload (simulated)
        |
POST /webhooks/facebook-lead
        |
  save raw lead (SQLite)
        |
  LLM qualification (OpenAI structured output)
        |
  Discord notification (timer stops here)
        |
  update lead + Google Sheet sync (background)
        |
  dashboard (http://127.0.0.1:8000)
```

## What it does

- **Webhook intake** for a simulated Facebook lead-ad payload (name, email, phone, company, number of doors, free-text message).
- **Storage:** every lead is saved to a local SQLite database. I chose SQLite so the project runs with no external setup.
- **LLM qualification** with a strict Pydantic schema:
  - `fit_score`: integer 1-5
  - `reason`: one sentence
  - `intent`: `low`, `medium`, or `high`
  - `suggested_reply`: a personalized first reply that mentions the company, door count, and pain point, and asks one next-step question
- **Notification** to Discord within seconds. Slack, Twilio SMS, and SMTP email are optional and only activate if their variables are set.
- **Google Sheet sync** (every qualified lead becomes a row), run in the background after delivery so it never adds latency to the message.
- **Latency measurement:** `end_to_end_seconds` is measured from webhook receipt to notification delivered, stored on the lead, and shown on the dashboard.
- **Safe fallbacks:** if the LLM call fails or times out, the lead is scored by a simple rule-based scorer and tagged `fallback`. If delivery fails, the lead is flagged `delivery_failed` instead of being lost.
- **Deduplication:** the same email and message within 5 minutes returns the existing lead instead of creating a duplicate.

## Requirements

- Python 3.10+
- An OpenAI API key
- A Discord webhook URL (Server settings > Integrations > Webhooks)
- Optional: a Google Sheet with the Apps Script below

## Setup

```bash
git clone <this-repo-url>
cd speed-to-lead-mvp

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# open .env and fill in your own values
```

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes | LLM scoring and reply drafting |
| `OPENAI_MODEL` | no | defaults to `gpt-4o-mini` |
| `DISCORD_WEBHOOK_URL` | recommended | where the notification is sent |
| `SHEET_WEBHOOK_URL` | no | Apps Script web app URL for the Google Sheet |
| `SHEET_SECRET` | no | shared secret checked by the Apps Script |
| `SLACK_WEBHOOK_URL` | no | optional Slack delivery |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_TO_PHONE` | no | optional SMS |
| `SMTP_HOST`, `SMTP_USER`, `ALERT_EMAIL_TO` | no | optional email |

`.env` is ignored by git. Never commit real keys. Only `.env.example` (placeholders) is committed.

If no notification channel is configured, the lead is delivered to the dashboard only (`INTERNAL_DASHBOARD`). If no OpenAI key is set, the header shows **AI: Heuristic Mode** and the rule-based scorer is used.

## Run

```bash
uvicorn app:app --reload --port 8000
```

Open http://127.0.0.1:8000. After any change to `.env`, stop the server (Ctrl+C) and start it again.

- Dashboard: http://127.0.0.1:8000
- API docs (Swagger): http://127.0.0.1:8000/docs

## Try it

**From the dashboard:** click **Reset demo data**, pick a preset (for example Sarah Jenkins, 185 doors), then click **Trigger Lead Qualification**. Check Discord, the lead detail view, and the Google Sheet.

**From the command line:**

```bash
curl -X POST http://127.0.0.1:8000/webhooks/facebook-lead \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "Sarah Jenkins",
    "email": "sarah@peaklineliving.com",
    "phone": "+1-555-014-2201",
    "company": "Peakline Living",
    "doors_managed": 185,
    "message": "We manage 185 doors across Austin and late rent collection is killing our cash flow, plus my staff spends 20 hours a week on manual bookkeeping. Can we schedule a demo this week?"
  }'
```

The exact field names come from the `LeadIn` model. If you get a validation error, open `/docs` and copy the example payload shown for this endpoint.

### Preset scenarios

| Preset | Doors | Message theme | Expected fit |
|---|---|---|---|
| Sarah Jenkins, Peakline Living | 185 | late rent, manual bookkeeping, wants a demo | 5 |
| David Morales, Horizon Property Partners | 45 | faster vendor invoicing and payments | 4 |
| Chloe Dupont, Atelier Stays | 12 | pricing inquiry | 3 or lower |
| Tyler Vance, individual tenant | 1 | wants to pay own rent | 1-2 |

Scores come from the model, not from the labels on the presets.

## Sample output

Example response from `POST /webhooks/facebook-lead` (values are illustrative):

```json
{
  "status": "processed",
  "lead_id": 1,
  "qualification": {
    "fit_score": 5,
    "reason": "Manages 185 doors with clear cash-flow and bookkeeping pain and explicit demo intent.",
    "intent": "high",
    "suggested_reply": "Hi Sarah, ... [personalized reply mentioning Peakline Living and 185 doors, ending with one question] ..."
  },
  "processing_ms": 3330,
  "end_to_end_seconds": 3.33,
  "target_seconds": 60,
  "under_60_seconds": true,
  "delivery_channel": "DISCORD",
  "delivery_failed": false,
  "scored_by": "llm",
  "deduplicated": false,
  "storage_engine": "sqlite"
}
```

Screenshots: `[add a Discord message screenshot here, with the webhook URL hidden]` and `[add a Google Sheet screenshot here]`.

## Google Sheet sync (optional)

1. Create a Google Sheet. In row 1 add these headers, one per column:
   `timestamp, name, email, phone, company, doors, message, fit_score, reason, intent, suggested_reply, end_to_end_seconds, delivery_channel`
2. Open **Extensions > Apps Script**, replace the contents with the script below, and set `SECRET` to a random string of your own.
3. **Deploy > New deployment > Web app**, **Execute as: Me**, **Who has access: Anyone**. Approve the permissions prompt and copy the `/exec` URL.
4. Put the URL in `SHEET_WEBHOOK_URL` and the same secret in `SHEET_SECRET` in `.env`, then restart the server.

```javascript
const SECRET = "replace-with-your-own-random-string";

function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);
    if (d.secret !== SECRET) {
      return ContentService.createTextOutput("unauthorized");
    }
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
    const row = sheet.getLastRow() + 1;

    // Make the phone cell plain text BEFORE writing, so "+1-555-..." is not read as a formula
    sheet.getRange(row, 4).setNumberFormat("@");

    sheet.getRange(row, 1, 1, 13).setValues([[
      new Date(), d.name, d.email, String(d.phone || ""), d.company, d.doors,
      d.message, d.fit_score, d.reason, d.intent, d.suggested_reply,
      d.end_to_end_seconds, d.delivery_channel
    ]]);
    return ContentService.createTextOutput("ok");
  } catch (err) {
    return ContentService.createTextOutput("error: " + err);
  }
}
```

If you edit the script later, use **Deploy > Manage deployments > Edit > New version**, or the old code keeps running.

## Project layout

```
app.py                         FastAPI app and routes
app_core/
  config.py                    settings loaded from .env
  models.py                    LeadIn, Qualification, ProcessLeadResponse
  database/repository.py       SQLite storage, dedupe, reset
  services/
    processor.py               pipeline: stage, score, notify, store, sheet sync
    qualifier.py               OpenAI structured-output scoring + fallback
    notifier.py                Discord / Slack / SMS / email delivery
    sheets.py                  Google Sheet sync
static/index.html              dashboard
```

The scoring prompt lives in `[path to the prompt file or the qualifier.py constant]`.

## How latency is measured

The timer starts when the webhook request is received (`time.perf_counter()` in `processor.py`) and stops after the notification send returns. The Google Sheet write runs after that point, in a background thread, so it is not counted and does not slow the message. `end_to_end_seconds` is saved on each lead and shown on the dashboard.

## Known limitations

- Leads are simulated. Nothing is sent to real prospects, and there is no live Facebook connection.
- The scorer depends on one LLM call. A retry and a queue would make this more robust.
- SQLite is local to one machine. The Google Sheet is the shared copy.
- No after-hours logic: a lead that arrives at night gets the same instant message as one in the afternoon.
- Phone numbers are stored as typed, with no validation.
- Latency depends on the LLM and the Discord API, so it varies from run to run.

## What I would do with more time

- Retry and queue the LLM and delivery calls, with alerts when they fail.
- Verify the webhook signature from Facebook and validate phone numbers.
- Send the drafted reply to the lead itself (SMS and email with a booking link) after a human approves it.
- Add after-hours rules and round-robin assignment to the team.
- Sync to the real CRM (GoHighLevel) instead of a Google Sheet.
- Run the experiment from my growth analysis: compare demo-booking rate for leads contacted in under 5 minutes against the old 22-hour flow.
- Add tests for scoring, fallback, dedupe, and latency storage.

## Security notes

- No API keys or webhook URLs are committed. Use `.env` locally and keep it out of git.
- The Apps Script URL plus its secret can write rows to the sheet, so treat both as secrets and delete the deployment when you are done.
- Revoke the OpenAI key and delete the Discord webhook after the review.