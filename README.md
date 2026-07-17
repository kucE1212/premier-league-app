# ⚽ Tipovačka — Premier League Prediction League (V1)

A self-hosted score-guessing game for a group of friends, backed by a Google
Sheet. Players open one link, register, pay the entry fee, type their secret
code and predict exact scores. Rounds lock at the first kickoff (Europe/Prague);
everyone's picks and points are revealed after. The Google Sheet is the
database, so the organiser can always eyeball or fix data by hand.

**Scoring:** exact score **3** · same goal difference **2** · right winner **1** · wrong **0**.
A **žolík (joker)** doubles the points of one chosen match (each player starts
with 3; up to 10 more can be bought at 50 Kč — max 13).

**Money:** entry fee 850 Kč (750 Kč to the prize bank + 100 Kč fee). Prize bank
is split **50 / 30 / 20 %** between the top three. The *Výhry a Žolíci* tab
computes the live bank automatically.

---

## What's in the app

| Tab | What it does |
|---|---|
| **Tabulka** | Live countdown to the round deadline + full leaderboard (ties: total → exact scores → goal diffs → draw). |
| **Zadat tipy** | Players enter their code and predict all matches of a round. Editable until lock. Shows saved/draft state and remaining jokers. |
| **Výsledky** | Everyone's picks + points per match, revealed once a round locks. Joker rows highlighted. |
| **Pravidla** | Full rules (Czech), 8 sections. |
| **Výhry a Žolíci** | Prize bank, prize split, joker overview per player. |
| **Registrace** | Self-service registration + payment QR code. |
| **Organizátor** | Password-protected: enter results, add rounds, manage players/jokers/active flags, approve registrations. |

On first run the app creates the four sheet tabs (Players, Fixtures,
Predictions, Registrations) and seeds all 8 rounds of fixtures automatically.
Players start empty — people register in the app and the organiser approves
them after payment. All writes are append-only or targeted; nothing is ever
destructively overwritten.

---

## Files to deploy (repo layout)

```
app.py                      ← the app
requirements.txt
qr_platba.png               ← payment QR image (REQUIRED for the Registration tab)
team_logos/                 ← club logos: arsenal.svg, chelsea.png, ... (optional,
                              colored badges are used as fallback)
.streamlit/config.toml      ← theme
```

**Never commit `.streamlit/secrets.toml`.** Secrets are pasted into Streamlit
Cloud instead (step 5).

---

## One-time setup (~15 min)

### 1. Create the Google Sheet
Make a new blank Google Sheet. From its URL copy the ID:
`https://docs.google.com/spreadsheets/d/`**`THIS_LONG_ID`**`/edit`

### 2. Create a Google service account
1. <https://console.cloud.google.com/> → create a project (any name).
2. **APIs & Services → Library** → enable **Google Sheets API** and **Google Drive API**.
3. **APIs & Services → Credentials → Create credentials → Service account** → click through.
4. Open the service account → **Keys → Add key → Create new key → JSON** — a `.json` file downloads.

### 3. Share the sheet with the service account
Copy `client_email` from the JSON (`...@...iam.gserviceaccount.com`) and give
that email **Editor** access on your Google Sheet (Share button).

### 4. Put the code on GitHub
Upload the repo layout above. Double-check `secrets.toml` is **not** included
(add `.streamlit/secrets.toml` to `.gitignore`).

### 5. Deploy on Streamlit Community Cloud (free)
1. <https://share.streamlit.io/> → sign in with GitHub → **New app** → pick the repo, main file `app.py`.
2. **Advanced settings → Secrets** — paste this, filled in with your values:

```toml
[app]
spreadsheet_id = "YOUR_SHEET_ID"
admin_code = "CHOOSE_A_STRONG_PASSWORD"   # organiser login — controls money & results!
# qr_payment_b64 = ""                     # optional: base64 QR instead of qr_platba.png

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
universe_domain = "googleapis.com"
```

   (Copy the `gcp_service_account` values from the downloaded JSON key.
   Keep `private_key` exactly as-is, with its `\n`s.)
3. **Deploy.** First load seeds the sheet. Share the link.

---

## Running the season

**Players:** open the link → *Registrace* → choose a code (3–20 letters/digits)
→ pay via the QR → wait for activation. Then *Zadat tipy* → enter code → fill
every match of the round → save. Tips can be changed any time until the round
locks at its first kickoff.

**Organiser** (*Organizátor* tab + admin code):
- **Zadat výsledky** — enter real scores after matches; leaderboard recalculates instantly.
- **Registrace** — after receiving a payment, add the registered player (they get 3 jokers and become active).
- **Hráči** — rename players, adjust joker counts (when someone buys extra), deactivate players.
- **Přidat kolo** — rounds 1–8 are pre-seeded; use this only for extra/custom rounds
  (kickoff format `2026-08-29T21:00`, Prague time).
- The **⚠️ Kontrola dat** expander flags any broken rows in the sheet with row numbers.

## Notes & gotchas

- **Kickoffs must stay plain text** in the Fixtures tab, format `2026-08-21T21:00`
  (Prague time). Don't let Google Sheets auto-convert them to dates.
- Player codes are effectively passwords — anyone who knows a code can edit that
  player's tips before the lock (rule 1.4). Tell people to keep them private.
- Predictions are append-only (latest save wins), so history is never lost.
- Streamlit's free tier puts the app to sleep after ~12 h without visitors; the
  first visitor then waits ~30–60 s while it wakes up. Harmless.
- Quick sanity test after deploying: register a test code, activate it in the
  Organiser tab, save tips on a phone, then delete/deactivate the test player.

Run locally: `pip install -r requirements.txt` → `streamlit run app.py`
(with a real `.streamlit/secrets.toml` in place).
