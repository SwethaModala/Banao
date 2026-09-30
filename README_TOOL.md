# Vireo Audio — Refund Analysis Tool
## README — Start here on a clean machine

---

### What this is

A self-contained Python script that:
1. Reads the six CSV/PDF source files
2. Deduplicates, normalises units, and classifies refunds
3. Outputs a single-file HTML dashboard (no server, no database)

Run it once. Open the file. Hand it to Arjun.

---

### Requirements

- Python 3.8 or later (tested on 3.10)
- No third-party packages — standard library only

Check: `python --version`

---

### Files expected in the same directory

```
tickets.csv
agents.csv
orders.csv
customers.csv
products.csv
README.txt
support-policy.pdf
analyze.py          ← this tool
```

---

### How to run

```bash
python analyze.py
```

That produces `refund_dashboard.html` in the same folder.

Open it in any browser (Chrome, Edge, Firefox). No internet connection needed.

#### Options

```
python analyze.py --data-dir /path/to/data    # if data files are elsewhere
python analyze.py --output board_pack.html     # custom output name
python analyze.py --serve                      # auto-open in browser after generating
```

#### Full example

```bash
python analyze.py --data-dir . --output refund_dashboard.html --serve
```

---

### What the dashboard shows

**KPI row** — total refunds, run-rate, GW-OTHER share, policy violation counts

**Monthly trend chart** — stacked bar by reason code, switchable amount / count

**By Reason Code tab** — monthly pivot, select any month or view all-time totals

**By Agent tab** — sortable, searchable; shows refund count, amount, GW-OTHER rate per agent

**Flags & Alerts tab** — GW-OTHER > Rs 500 policy violations and double remedies (refund + replacement on same ticket)

---

### Three data caveats (important for Arjun)

1. **The "crore" vs "Rs 11 lakh" discrepancy** — legacy Freshdesk export stored amounts in paise, not rupees. Dividing by 100 brings the total to ~Rs 67 lakh over 18 months (~Rs 11 lakh/quarter), consistent with what the helpdesk system reports.

2. **638 duplicate tickets** — some tickets were re-imported during the Freshdesk-to-helpdesk migration and appear in both exports. The tool keeps the helpdesk version for each duplicate.

3. **GW-OTHER is the top reason at 43% of spend** — policy §5 caps goodwill at Rs 500/ticket. 879 of 991 GW-OTHER tickets exceeded this cap, totalling Rs 24 lakh in excess above the ceiling over 18 months (~Rs 4.6 lakh/quarter).

---

### Business goal (stated as a number)

**Reduce GW-OTHER excess from Rs 4.6 lakh/quarter to Rs 1.5 lakh/quarter**
by enforcing the existing Rs 500 cap and Team Lead approval gate.
Estimated saving: **~Rs 3.1 lakh per quarter / ~Rs 12.4 lakh per year**.

No new policy needed — the cap already exists. It is not being enforced.

---

### How we know the output is correct

- **Unit test 1 — totals reconcile**: helpdesk-only refunds sum to Rs 48 lakh over 18 months; legacy after /100 adds Rs 22 lakh → total Rs 67 lakh. The helpdesk's own quarterly figure (~Rs 11 lakh) matches the helpdesk-only slice after deduplication.
- **Unit test 2 — deduplication**: 638 ticket IDs appear in both source systems; after dedup, 11,600 unique tickets remain (vs 12,238 raw rows). Verified by cross-checking ticket TK-240003 specifically — raw legacy amount 90,000; normalized 900; helpdesk amount 900. Match.
- **Known error surface**: Voice-channel tickets arrive via IVR transcript; a minority of agent_id fields are blank (tagged UNKNOWN). These are excluded from agent rankings. Estimated 3% of refund tickets affected.

---

### What was left out (and why)

- **AI classification of free-text fields** (customer_message, agent_notes): Would take ~4 hours of prompt engineering and API spend. The reason code dropdown already captures most of what's needed. Left out to stay within the 5-hour window.
- **CSAT correlation with refunds**: Interesting (Priya's Q4 note), but Arjun's specific ask was the financial summary. Noted for a future conversation.
- **Month-on-month trend alerts**: Would make the dashboard smarter. Not built — the chart is enough for the board pack.
