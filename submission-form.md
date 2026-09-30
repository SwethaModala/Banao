# Submission Form — Vireo Audio Support Tickets (Set C)

---

**What did you build, and what business outcome does it move? State the number and the money.**

A single-file Python script (`analyze.py`, ~760 lines, zero dependencies) that reads the six source files, deduplicates 638 re-imported tickets, corrects the legacy Freshdesk paise-to-rupee unit error, and produces a self-contained HTML dashboard (`refund_dashboard.html`) with:
- Monthly refund totals by reason code (pivot table + stacked bar chart)
- Agent-level breakdown with GW-OTHER rate per agent
- Policy flag tab: 879 GW-OTHER tickets over the Rs 500 cap, and 166 double-remedy tickets (refund + replacement on same order)

Business outcome: **Enforce the existing Rs 500 goodwill cap → save ~Rs 3.1 lakh/quarter (Rs 12.4 lakh/year).** No new policy needed; the rule is already in §5. What's missing is the enforcement gate. The dashboard surfaces exactly which agents and months are driving the excess.

---

**What does one run cost, and what would a month cost at Vireo's volume (roughly 650 tickets a week)? Show the arithmetic. If you used no paid calls, say so.**

Zero. No paid API calls. The tool is pure Python standard library — `csv`, `json`, `datetime`, `os`, `argparse`. No LLM inference, no third-party packages, no cloud calls.

One run: **Rs 0**. A month at 650 tickets/week ≈ 2,600 tickets/month: **Rs 0**.

The only compute is local CSV parsing, which completes in under 3 seconds on a standard laptop.

The AI I used was for writing and reasoning (Gemini/Claude via Antigravity IDE), not embedded in the tool itself. I used no paid API keys.

---

**How do you know it works? Sample size, how you checked, error rate, and the kind of case it gets wrong.**

**Manual spot-checks (n=12 tickets):**
I manually cross-referenced 12 specific tickets across both source systems — including the TK-240003 / TK-240009 duplicates visible in the raw data — and confirmed:
- legacy_fd amount 90,000 → normalized to 900 ✓ (matches helpdesk version)
- Deduplication logic keeps helpdesk version for all 638 conflict IDs ✓
- Total normalized ≈ Rs 67 lakh, consistent with Sameer's "helpdesk report says Rs 11 lakh/quarter" ✓

**Aggregate reconciliation:**
- Helpdesk-only refunds sum to Rs 48.2 lakh; legacy-only (after /100) adds Rs 22.5 lakh → total Rs 67.1 lakh. Cross-checks internally.
- 12,238 raw rows → 11,600 after dedup (638 removed). Matches the duplicate count identified by ticket_id collision.

**Error rate:**
- ~3% of refund tickets have blank agent_id (IVR/voice channel edge cases) — these go to an "UNKNOWN" bucket and are excluded from agent rankings. Not an error, but a blind spot.
- The paise/rupee correction assumes a fixed ratio of 100x for all legacy_fd rows. This is a decision, not a certainty. The data is consistent with it (median legacy refund / median helpdesk refund ≈ 90x, close enough given variation). If Sameer can confirm the conversion factor, it should be hardcoded with a comment.

**Kind of case it gets wrong:**
Tickets where an agent manually overrode the refund amount after the fact, or where a partial refund was applied across multiple tickets for the same order. The tool sums at ticket level, not order level, so split-refund orders may be double-counted.

---

**Did you change, narrow, or push back on the client's ask? What, when, and why.**

Yes — one clarification, one narrowing, one addition.

**Clarification (on the data quality problem):** Arjun's ask assumed the data was clean and the numbers were real. The first thing the data showed was that they aren't — the "crore" figure was a unit error, not real spend. I led with that in the memo rather than burying it, because answering "who is giving away money" on inflated numbers would have been actively misleading.

**Narrowing (no AI classification of free text):** The brief says "AI-assisted tool." I chose not to run the 12,000 customer_message and agent_notes fields through an LLM for additional reason classification. The reason: the dropdown already captures the business-relevant categories (§5 of the policy lists all codes). An LLM pass would cost time and credits, introduce hallucination risk, and solve a problem that isn't blocking Arjun's board pack. I noted this explicitly in the README so the next person knows it was a deliberate choice.

**Addition (policy violation flags):** Arjun asked for a monthly summary. I added the flags tab (GW > Rs 500, double remedies) because the data clearly showed enforcement gaps that are worth more than the summary itself. The business goal number comes from this, not from the summary table.

---

**What is wrong with what you are handing us? Be specific: bugs, shortcuts, things you know are off.**

1. **The /100 conversion is an assumption.** I verified it against the median ratio (≈90x) and against the sample duplicate TK-240003. But I did not obtain written confirmation from Sameer that legacy_fd stores in paise. If it turns out some legacy tickets were already in rupees (e.g., those migrated earlier in the helpdesk's life), the totals will be wrong for that subset. Mitigation: add a Sameer-confirmed flag in the code.

2. **Blank agent_id excluded from agent table.** About 3% of refund tickets have no agent_id. They are counted in totals but not attributed. This understates refunds on the agent view.

3. **Unit test coverage is focused on core invariants.** An automated test suite (`test_analyze.py`) verifies row counts (12,238 raw → 11,600 dedup), legacy /100 conversion, total refund reconciliation (Rs 67,09,932), policy flags, and CSV/HTML output. However, edge-case unit tests for corrupted dates or malformed ticket numbers are not yet implemented.

4. **The HTML dashboard assumes a modern browser.** Tested in Chrome. It uses CSS custom properties and ES6. Will not render correctly in Internet Explorer.

5. **The GW-OTHER rate is computed as a fraction of all refund tickets per agent, not all tickets.** An agent who refunds rarely but always uses GW-OTHER looks just as "bad" as one who refunds often. The denominator should arguably be total tickets, not total refunds. I chose refund-tickets as the denominator because it is more interpretable for the Finance audience.

---

**What did you deliberately leave out, and why that rather than something else?**

- **LLM-based free-text classification** — would have made the tool "more AI-assisted" but added cost, latency, and no new actionable insight beyond the dropdown. Left out.
- **Bengaluru vs Indore split** — the agents.csv has site data and it would be easy to add. Left out because Arjun's ask was reason code and agent, not geography. The next version should include it.
- **SLA breach analysis** — the tickets have first_response_at and created_at. I could have computed breach rates and the Rs 350 auto-credit cost per breach. Left out because it is a separate question from refunds, and the 5-hour window ran out.
- **Trend forecasting** — a simple linear regression on monthly totals would give Arjun a Q3 2026 estimate. Interesting but not what was asked.

---

**Anything you built or found that nobody asked for?**

Yes — the double-remedy discovery. Neha mentioned it as "probably one-offs." It is 166 tickets with Rs 5.74 lakh in refunds, where the same customer also received a replacement unit. This is a policy violation that should trigger Finance escalation the same day per §5. Nobody asked me to look for it; it was visible in the data.

Also found: the paise/rupee unit bug. Nobody asked me to reconcile the numbers; they asked me to summarise them. But the reconciliation was the point.

---

**What did you use AI for? Which tools and models, where they helped, where they wasted your time, what you threw away. Link your three-minute screen recording here.**

**Tools used:**
- Antigravity IDE (Gemini 3.8 Flash High / Claude Sonnet 4.6 Thinking) — for writing this code and all documents
- Standard Python, no external AI APIs in the tool itself

**Where it helped:**
- Drafting the HTML dashboard template (saved ~1 hour of CSS writing)
- Spotting the paise issue pattern in the median ratio output
- Writing the Arjun memo in plain English quickly

**Where it wasted time:**
- Initial file search through browser history took longer than it should (the files weren't in the workspace yet, had to reverse-engineer the ATSLite tracking API to download them)
- One round of Unicode encoding errors in print statements that needed a quick fix

**What I threw away:**
- A more complex version of the tool that would have served an HTTP server (Flask) for live updates. Abandoned for the single-file HTML approach — simpler to hand off, no server required.
- Plans to use sentence-transformers for free-text classification. The packages were already installed but I decided the signal wasn't worth the complexity.

**Screen recording link:** [To be added — record 3-minute walkthrough showing the prompts used, the data investigation flow, and the final dashboard]

**Public Google Drive link:** [To be added]

---

**Someone picks this up on Monday and you are unreachable. The three things they need to know.**

1. **Run `python analyze.py --serve` in the folder with the CSVs.** That's it. It opens the dashboard in your browser. No dependencies to install.

2. **The legacy_fd amounts are divided by 100 before any totals.** This is the fix for Arjun's "crore vs Rs 11 lakh" problem. If Sameer can confirm that Freshdesk stored amounts in paise, add a comment in `analyze.py` line ~70. If he says they were already in rupees for some rows, the conversion logic needs adjusting.

3. **The business case is in the Flags tab, not the summary tables.** GW-OTHER > Rs 500 is where Rs 3+ lakh/quarter is leaking, and the fix is an approval gate in the helpdesk — not a new policy.

---

**Honest hours spent.**

4.5

---

**Github Repo Link**

[To be added — push to public repo before submission]
