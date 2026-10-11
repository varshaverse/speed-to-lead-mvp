#!/usr/bin/env bash
# scripts/send_fake_lead.sh
# Sends a simulated Facebook Lead Ad webhook payload to the Speed-to-Lead endpoint.

ENDPOINT="${1:-http://127.0.0.1:8000/webhooks/facebook-lead}"

echo "🚀 Sending simulated Facebook Lead Ad payload to: $ENDPOINT"

curl -X POST "$ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: speed-to-lead-secret" \
  -d '{
    "name": "Sarah Jenkins",
    "email": "sarah@peaklineliving.com",
    "phone": "+1-555-014-2201",
    "company": "Peakline Living",
    "doors": 185,
    "message": "We manage 185 doors across Austin and late rent collection is killing our cash flow, plus my staff spends 20 hours a week on manual bookkeeping. Can we schedule a demo this week?"
  }'

echo ""
echo "✅ Finished webhook request."
