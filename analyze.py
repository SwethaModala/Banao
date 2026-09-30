"""
Vireo Audio — Refund Analysis Tool
Generates monthly refund summary by reason code and by agent.
"""

import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
import http.server
import threading
import webbrowser

def load_csv(filename):
    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        return list(csv.DictReader(f))

def safe_float(val):
    try:
        v = float(str(val).strip())
        return v if v > 0 else 0
    except:
        return 0

def process_data(data_dir='.'):
    tickets = load_csv(os.path.join(data_dir, 'tickets.csv'))
    agents_list = load_csv(os.path.join(data_dir, 'agents.csv'))

    agents_by_id = {}
    for a in agents_list:
        aid = a.get('agent_id', '')
        if aid and aid not in agents_by_id:
            agents_by_id[aid] = a

    # Deduplicate: prefer helpdesk version over legacy_fd
    helpdesk_by_id, legacy_by_id = {}, {}
    for t in tickets:
        if t.get('source_system') == 'helpdesk':
            helpdesk_by_id[t['ticket_id']] = t
        else:
            legacy_by_id[t['ticket_id']] = t

    clean_tickets = list(helpdesk_by_id.values())
    for tid, t in legacy_by_id.items():
        if tid not in helpdesk_by_id:
            clean_tickets.append(t)

    # Normalize amounts (legacy_fd stores in paise, not rupees)
    for t in clean_tickets:
        raw = safe_float(t.get('refund_amount_inr', ''))
        t['norm_refund'] = raw / 100.0 if (t.get('source_system') == 'legacy_fd' and raw > 0) else raw

    refund_tickets = [t for t in clean_tickets if t['norm_refund'] > 0]

    # Monthly pivot: {month: {reason_code: {count, amount}}}
    monthly_reason = defaultdict(lambda: defaultdict(lambda: {'count': 0, 'amount': 0.0}))
    # Monthly pivot: {month: {agent_id: {count, amount}}}
    monthly_agent = defaultdict(lambda: defaultdict(lambda: {'count': 0, 'amount': 0.0, 'gw_count': 0}))

    flags = []  # notable flags: policy violations etc.

    for t in refund_tickets:
        try:
            dt = datetime.strptime(t['created_at'][:10], '%Y-%m-%d')
            month = dt.strftime('%Y-%m')
        except:
            continue

        reason = t.get('refund_reason_code') or 'UNKNOWN'
        agent_id = t.get('agent_id') or 'UNKNOWN'
        amt = t['norm_refund']

        monthly_reason[month][reason]['count'] += 1
        monthly_reason[month][reason]['amount'] += amt

        monthly_agent[month][agent_id]['count'] += 1
        monthly_agent[month][agent_id]['amount'] += amt
        if reason == 'GW-OTHER':
            monthly_agent[month][agent_id]['gw_count'] += 1

        # Flag policy violations
        if reason == 'GW-OTHER' and amt > 500:
            flags.append({
                'type': 'GW_OVER_500',
                'ticket_id': t['ticket_id'],
                'month': month,
                'agent_id': agent_id,
                'agent_name': agents_by_id.get(agent_id, {}).get('name', 'Unknown'),
                'amount': amt,
                'excess': amt - 500,
            })
        if t.get('replacement_issued') == 'Y' and amt > 0:
            flags.append({
                'type': 'DOUBLE_REMEDY',
                'ticket_id': t['ticket_id'],
                'month': month,
                'agent_id': agent_id,
                'agent_name': agents_by_id.get(agent_id, {}).get('name', 'Unknown'),
                'amount': amt,
            })

    # Build output structure
    months = sorted(monthly_reason.keys())
    all_reasons = sorted(set(r for m in monthly_reason.values() for r in m))
    all_agents = sorted(set(a for m in monthly_agent.values() for a in m))

    reason_summary = []
    for month in months:
        row = {'month': month}
        total = 0
        for reason in all_reasons:
            v = monthly_reason[month].get(reason, {'count': 0, 'amount': 0})
            row[f'{reason}_count'] = v['count']
            row[f'{reason}_amount'] = round(v['amount'], 2)
            total += v['amount']
        row['total_amount'] = round(total, 2)
        reason_summary.append(row)

    agent_summary = []
    for month in months:
        for agent_id in all_agents:
            v = monthly_agent[month].get(agent_id, None)
            if v and v['count'] > 0:
                info = agents_by_id.get(agent_id, {})
                agent_summary.append({
                    'month': month,
                    'agent_id': agent_id,
                    'agent_name': info.get('name', 'Unknown'),
                    'team': info.get('team', 'Unknown'),
                    'site': info.get('site', 'Unknown'),
                    'refund_count': v['count'],
                    'refund_amount': round(v['amount'], 2),
                    'gw_other_count': v['gw_count'],
                    'gw_other_rate_pct': round(v['gw_count'] / v['count'] * 100, 1) if v['count'] else 0,
                })

    gw_violations_count = sum(1 for f in flags if f['type'] == 'GW_OVER_500')
    gw_excess_total = sum(f.get('excess', 0) for f in flags if f['type'] == 'GW_OVER_500')
    double_remedy_count = sum(1 for f in flags if f['type'] == 'DOUBLE_REMEDY')

    summary = {
        'generated_at': datetime.now().isoformat(),
        'data_notes': [
            '638 tickets appeared in both legacy_fd and helpdesk (post-migration re-import); helpdesk version kept.',
            'legacy_fd refund amounts divided by 100 to convert from Freshdesk native units (paise) to rupees.',
            'This reconciles the ~Rs 11 lakh/quarter helpdesk figure vs the inflated export Arjun saw.',
        ],
        'totals': {
            'clean_ticket_count': len(clean_tickets),
            'refund_ticket_count': len(refund_tickets),
            'total_refund_inr': round(sum(t['norm_refund'] for t in refund_tickets), 2),
        },
        'flags': {
            'gw_over_500_count': gw_violations_count,
            'gw_over_500_excess_inr': round(gw_excess_total, 2),
            'double_remedy_count': double_remedy_count,
        }
    }

    return {
        'summary': summary,
        'monthly_by_reason': reason_summary,
        'monthly_by_agent': agent_summary,
        'all_reasons': all_reasons,
        'flags': flags,
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Vireo Audio — Refund Summary</title>
  <meta name="description" content="Monthly refund summary by reason code and agent for Vireo Audio support desk — for board pack.">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    :root {
      --bg: #0d1117;
      --surface: #161b22;
      --surface2: #1c232e;
      --border: #30363d;
      --text: #e6edf3;
      --muted: #8b949e;
      --accent: #58a6ff;
      --accent2: #3fb950;
      --danger: #f85149;
      --warning: #d29922;
      --purple: #bc8cff;
      --card-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }

    header {
      background: linear-gradient(135deg, #1a2a4a 0%, #0d1117 60%);
      border-bottom: 1px solid var(--border);
      padding: 28px 40px;
      display: flex; align-items: center; justify-content: space-between;
    }
    header h1 { font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em; }
    header h1 span { color: var(--accent); }
    header .subtitle { color: var(--muted); font-size: 0.85rem; margin-top: 4px; }
    .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }
    .badge-blue { background: rgba(88,166,255,0.15); color: var(--accent); border: 1px solid rgba(88,166,255,0.3); }

    .container { max-width: 1400px; margin: 0 auto; padding: 32px 40px; }

    .note-bar {
      background: rgba(210,153,34,0.1);
      border: 1px solid rgba(210,153,34,0.3);
      border-radius: 8px;
      padding: 14px 20px;
      margin-bottom: 28px;
      font-size: 0.82rem;
      color: #e3b341;
      line-height: 1.5;
    }
    .note-bar strong { display: block; margin-bottom: 4px; }

    .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 32px; }
    .kpi-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      position: relative;
      overflow: hidden;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    .kpi-card:hover { transform: translateY(-2px); box-shadow: var(--card-shadow); }
    .kpi-card .label { font-size: 0.78rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
    .kpi-card .value { font-size: 1.9rem; font-weight: 700; margin: 8px 0 4px; line-height: 1; }
    .kpi-card .sub { font-size: 0.8rem; color: var(--muted); }
    .kpi-card.danger { border-color: rgba(248,81,73,0.4); }
    .kpi-card.danger .value { color: var(--danger); }
    .kpi-card.warning { border-color: rgba(210,153,34,0.4); }
    .kpi-card.warning .value { color: var(--warning); }
    .kpi-card.success .value { color: var(--accent2); }
    .kpi-card.accent .value { color: var(--accent); }

    .section-title {
      font-size: 1.1rem; font-weight: 600; margin-bottom: 16px; padding-bottom: 10px;
      border-bottom: 1px solid var(--border);
      display: flex; align-items: center; gap: 10px;
    }

    /* Controls */
    .controls { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; align-items: center; }
    .controls select, .controls input {
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 8px 14px;
      border-radius: 8px;
      font-family: inherit;
      font-size: 0.85rem;
      cursor: pointer;
      transition: border-color 0.2s;
    }
    .controls select:hover, .controls input:hover { border-color: var(--accent); }
    .controls label { font-size: 0.83rem; color: var(--muted); }

    /* Tables */
    .table-wrap { overflow-x: auto; border-radius: 12px; border: 1px solid var(--border); margin-bottom: 32px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
    thead tr { background: var(--surface2); }
    thead th {
      padding: 12px 14px; text-align: right; font-weight: 600;
      color: var(--muted); font-size: 0.75rem; text-transform: uppercase;
      letter-spacing: 0.05em; border-bottom: 1px solid var(--border);
      cursor: pointer; user-select: none; white-space: nowrap;
    }
    thead th:first-child, thead th.left { text-align: left; }
    thead th:hover { color: var(--text); }
    tbody tr { transition: background 0.15s; }
    tbody tr:hover { background: rgba(88,166,255,0.05); }
    tbody td { padding: 10px 14px; border-bottom: 1px solid rgba(48,54,61,0.5); text-align: right; }
    tbody td:first-child, tbody td.left { text-align: left; }
    tbody tr:last-child td { border-bottom: none; }

    .amount { font-variant-numeric: tabular-nums; }
    .pill {
      display: inline-block; padding: 2px 8px; border-radius: 12px;
      font-size: 0.72rem; font-weight: 600;
    }
    .pill-red { background: rgba(248,81,73,0.15); color: var(--danger); }
    .pill-yellow { background: rgba(210,153,34,0.15); color: var(--warning); }
    .pill-green { background: rgba(63,185,80,0.15); color: var(--accent2); }
    .pill-blue { background: rgba(88,166,255,0.15); color: var(--accent); }

    .bar-cell { position: relative; }
    .bar-bg { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 2px; transition: width 0.3s; }

    /* Tabs */
    .tabs { display: flex; gap: 2px; margin-bottom: 20px; border-bottom: 1px solid var(--border); }
    .tab-btn {
      padding: 10px 20px; border: none; background: none; color: var(--muted);
      cursor: pointer; font-family: inherit; font-size: 0.88rem; font-weight: 500;
      border-bottom: 2px solid transparent; margin-bottom: -1px;
      transition: color 0.2s, border-color 0.2s;
    }
    .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
    .tab-btn:hover { color: var(--text); }
    .tab-panel { display: none; }
    .tab-panel.active { display: block; }

    /* Chart */
    .chart-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin-bottom: 32px; }
    .bar-chart { display: flex; align-items: flex-end; gap: 6px; height: 180px; margin-top: 20px; }
    .bar-group { flex: 1; display: flex; flex-direction: column; align-items: center; }
    .bar-stack { width: 100%; display: flex; flex-direction: column-reverse; cursor: pointer; }
    .bar-segment { transition: opacity 0.2s; }
    .bar-segment:hover { opacity: 0.8; }
    .bar-label { font-size: 0.65rem; color: var(--muted); margin-top: 4px; text-align: center; transform: rotate(-30deg); }

    .legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; }
    .legend-item { display: flex; align-items: center; gap: 6px; font-size: 0.78rem; }
    .legend-dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }

    .tooltip {
      position: fixed; background: var(--surface); border: 1px solid var(--border);
      border-radius: 8px; padding: 10px 14px; pointer-events: none;
      font-size: 0.8rem; z-index: 1000; display: none;
      box-shadow: 0 8px 24px rgba(0,0,0,0.5); max-width: 280px;
    }

    /* Flags / alerts */
    .flag-item {
      display: flex; align-items: flex-start; gap: 12px;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;
      font-size: 0.82rem;
    }
    .flag-item .icon { font-size: 1rem; flex-shrink: 0; }
    .flag-item .meta { color: var(--muted); font-size: 0.75rem; margin-top: 2px; }

    .search-box {
      width: 100%; max-width: 320px;
      background: var(--surface); border: 1px solid var(--border);
      color: var(--text); padding: 9px 14px; border-radius: 8px;
      font-family: inherit; font-size: 0.85rem;
    }
    .search-box:focus { outline: none; border-color: var(--accent); }

    footer {
      text-align: center; padding: 24px; color: var(--muted);
      font-size: 0.78rem; border-top: 1px solid var(--border);
      margin-top: 20px;
    }

    @media (max-width: 768px) {
      .container, header { padding: 16px 16px; }
      .kpi-grid { grid-template-columns: repeat(2, 1fr); }
    }
  </style>
</head>
<body>
<div id="tooltip" class="tooltip"></div>

<header>
  <div>
    <h1>Vireo Audio — <span>Refund Intelligence</span></h1>
    <div class="subtitle">Monthly summary by reason code &amp; agent · Jan 2025 – Jun 2026 · <span id="gen-time"></span></div>
  </div>
  <div><span class="badge badge-blue" id="ticket-count-badge">— tickets</span></div>
</header>

<div class="container">

  <div class="note-bar">
    <strong>⚠ Data quality note</strong>
    638 tickets appeared in both legacy Freshdesk export and current helpdesk (post-migration re-import) — helpdesk version kept.
    Legacy refund amounts are stored in Freshdesk's native unit (paise); divided by 100 to convert to rupees.
    This reconciles Arjun's "crore" figure vs the Rs 11 lakh/quarter that the helpdesk system reports.
  </div>

  <div class="kpi-grid" id="kpi-grid"></div>

  <div class="section-title">📊 Monthly Refund Trend</div>
  <div class="chart-wrap">
    <div class="controls">
      <label>View: </label>
      <select id="chart-mode" onchange="renderChart()">
        <option value="amount">By Amount (Rs)</option>
        <option value="count">By Count</option>
      </select>
    </div>
    <div class="bar-chart" id="bar-chart"></div>
    <div class="legend" id="chart-legend"></div>
  </div>

  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('reason')" id="tab-reason">By Reason Code</button>
    <button class="tab-btn" onclick="switchTab('agent')" id="tab-agent">By Agent</button>
    <button class="tab-btn" onclick="switchTab('flags')" id="tab-flags">⚠ Flags &amp; Alerts</button>
  </div>

  <!-- Reason Code Tab -->
  <div class="tab-panel active" id="panel-reason">
    <div class="controls">
      <label>Month: </label>
      <select id="reason-month" onchange="renderReasonTable()">
        <option value="all">All months (totals)</option>
      </select>
    </div>
    <div class="table-wrap">
      <table id="reason-table">
        <thead id="reason-thead"></thead>
        <tbody id="reason-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- Agent Tab -->
  <div class="tab-panel" id="panel-agent">
    <div class="controls">
      <label>Month: </label>
      <select id="agent-month" onchange="renderAgentTable()">
        <option value="all">All months (totals)</option>
      </select>
      <input class="search-box" type="text" id="agent-search" placeholder="Search agent or team..." oninput="renderAgentTable()">
    </div>
    <div class="table-wrap">
      <table id="agent-table">
        <thead>
          <tr>
            <th class="left" onclick="sortAgent('agent_name')">Agent ↕</th>
            <th class="left" onclick="sortAgent('team')">Team ↕</th>
            <th onclick="sortAgent('refund_count')">Count ↕</th>
            <th onclick="sortAgent('refund_amount')">Amount (Rs) ↕</th>
            <th onclick="sortAgent('gw_other_count')">GW-OTHER # ↕</th>
            <th onclick="sortAgent('gw_other_rate_pct')">GW% ↕</th>
          </tr>
        </thead>
        <tbody id="agent-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- Flags Tab -->
  <div class="tab-panel" id="panel-flags">
    <div id="flags-content"></div>
  </div>

</div>

<footer>Vireo Audio · Support Desk Refund Analysis · Internal — for board pack · Generated <span id="gen-time2"></span></footer>

<script>
const DATA = __DATA_PLACEHOLDER__;

const REASON_COLORS = {
  'GW-OTHER': '#f85149',
  'RETURN-QC-OK': '#58a6ff',
  'DUP-PAYMENT': '#d29922',
  'CANCEL': '#bc8cff',
  'DOA-REPL': '#3fb950',
  'WTY-BUYBACK': '#ff9500',
  'PRICE-ADJ': '#2ea043',
  'LOST-TRANSIT': '#a5d6ff',
  'UNKNOWN': '#484f58',
};

const fmt = (n) => '₹' + Math.round(n).toLocaleString('en-IN');
const fmtN = (n) => Math.round(n).toLocaleString('en-IN');

let agentSort = {col: 'refund_amount', dir: -1};

function init() {
  const now = new Date(DATA.summary.generated_at);
  document.getElementById('gen-time').textContent = now.toLocaleDateString('en-IN', {day:'numeric',month:'short',year:'numeric'});
  document.getElementById('gen-time2').textContent = now.toLocaleDateString('en-IN', {day:'numeric',month:'short',year:'numeric'});
  document.getElementById('ticket-count-badge').textContent = fmtN(DATA.summary.totals.clean_ticket_count) + ' tickets (deduplicated)';

  renderKPIs();
  populateMonthDropdowns();
  renderChart();
  renderReasonTable();
  renderAgentTable();
  renderFlags();
}

function renderKPIs() {
  const s = DATA.summary;
  const totalQ = DATA.monthly_by_reason.reduce((acc, r) => acc + r.total_amount, 0) / DATA.monthly_by_reason.length * 3;
  const gw_total = DATA.monthly_by_reason.reduce((acc, r) => acc + (r['GW-OTHER_amount'] || 0), 0);
  const total = s.totals.total_refund_inr;
  const gw_pct = (gw_total / total * 100).toFixed(1);

  const kpis = [
    {label: 'Total Refunds (18mo)', value: fmt(total), sub: `Avg ${fmt(total/18)}/month`, cls: 'accent'},
    {label: 'Approx Quarterly Run-Rate', value: fmt(totalQ), sub: 'Based on 18-month avg', cls: ''},
    {label: 'GW-OTHER Share', value: gw_pct + '%', sub: `${fmt(gw_total)} total — #1 reason`, cls: 'danger'},
    {label: 'GW > ₹500 Violations', value: fmtN(s.flags.gw_over_500_count), sub: `₹${Math.round(s.flags.gw_over_500_excess_inr).toLocaleString('en-IN')} excess paid`, cls: 'danger'},
    {label: 'Double Remedies', value: fmtN(s.flags.double_remedy_count), sub: 'Refund + replacement (policy breach)', cls: 'warning'},
    {label: 'Refund Tickets', value: fmtN(s.totals.refund_ticket_count), sub: `of ${fmtN(s.totals.clean_ticket_count)} total`, cls: 'success'},
  ];

  document.getElementById('kpi-grid').innerHTML = kpis.map(k =>
    `<div class="kpi-card ${k.cls}">
      <div class="label">${k.label}</div>
      <div class="value">${k.value}</div>
      <div class="sub">${k.sub}</div>
    </div>`
  ).join('');
}

function populateMonthDropdowns() {
  const months = DATA.monthly_by_reason.map(r => r.month).sort();
  ['reason-month', 'agent-month'].forEach(id => {
    const sel = document.getElementById(id);
    months.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m;
      sel.appendChild(opt);
    });
  });
}

function renderChart() {
  const mode = document.getElementById('chart-mode').value;
  const months = DATA.monthly_by_reason.sort((a,b) => a.month.localeCompare(b.month));
  const reasons = DATA.all_reasons;
  const maxVal = Math.max(...months.map(m => mode === 'amount' ? m.total_amount : reasons.reduce((s,r) => s + (m[r+'_count']||0), 0)));

  const chart = document.getElementById('bar-chart');
  chart.innerHTML = months.map(m => {
    const totalVal = mode === 'amount' ? m.total_amount : reasons.reduce((s,r) => s + (m[r+'_count']||0), 0);
    const segments = reasons.map(r => {
      const val = mode === 'amount' ? (m[r+'_amount']||0) : (m[r+'_count']||0);
      const pct = maxVal > 0 ? (val / maxVal * 100) : 0;
      return pct > 0 ? `<div class="bar-segment" style="height:${pct}%;background:${REASON_COLORS[r]||'#58a6ff'}" 
        onmouseenter="showTip(event,'${m.month}<br>${r}: ${mode==='amount'?fmt(val):fmtN(val)}')" onmouseleave="hideTip()"></div>` : '';
    }).join('');
    return `<div class="bar-group">
      <div class="bar-stack" style="height:100%" title="${m.month}: ${mode==='amount'?fmt(totalVal):fmtN(totalVal)}">${segments}</div>
      <div class="bar-label">${m.month.slice(5)}<br>${m.month.slice(0,4)}</div>
    </div>`;
  }).join('');

  document.getElementById('chart-legend').innerHTML = reasons.map(r =>
    `<div class="legend-item"><div class="legend-dot" style="background:${REASON_COLORS[r]||'#58a6ff'}"></div>${r}</div>`
  ).join('');
}

function renderReasonTable() {
  const month = document.getElementById('reason-month').value;
  const reasons = DATA.all_reasons;

  // Header
  document.getElementById('reason-thead').innerHTML = `<tr>
    <th class="left">Month</th>
    ${reasons.map(r => `<th style="color:${REASON_COLORS[r]||'var(--muted)'}">${r}</th>`).join('')}
    <th>Total (Rs)</th>
  </tr>`;

  let rows;
  if (month === 'all') {
    // Aggregate all months
    const totals = {};
    reasons.forEach(r => { totals[r] = {count: 0, amount: 0}; });
    let grand = 0;
    DATA.monthly_by_reason.forEach(m => {
      reasons.forEach(r => {
        totals[r].count += m[r+'_count']||0;
        totals[r].amount += m[r+'_amount']||0;
        grand += m[r+'_amount']||0;
      });
    });
    // deduplicate grand total
    grand = DATA.monthly_by_reason.reduce((s, m) => s + m.total_amount, 0);
    rows = [`<tr style="font-weight:600;background:rgba(88,166,255,0.05)">
      <td class="left">All Months</td>
      ${reasons.map(r => `<td class="amount">${totals[r].count > 0 ? fmt(totals[r].amount) + '<br><span style="color:var(--muted);font-size:0.75rem">' + fmtN(totals[r].count) + ' tickets</span>' : '—'}</td>`).join('')}
      <td class="amount" style="color:var(--accent)">${fmt(grand)}</td>
    </tr>`];
  } else {
    const mData = DATA.monthly_by_reason.find(m => m.month === month);
    if (!mData) { rows = ['<tr><td colspan="20" style="text-align:center;color:var(--muted);padding:20px">No data</td></tr>']; }
    else {
      rows = [`<tr>
        <td class="left">${mData.month}</td>
        ${reasons.map(r => `<td class="amount">${mData[r+'_count'] ? fmt(mData[r+'_amount']) + '<br><span style="color:var(--muted);font-size:0.75rem">'+fmtN(mData[r+'_count'])+' tickets</span>' : '—'}</td>`).join('')}
        <td class="amount" style="color:var(--accent)">${fmt(mData.total_amount)}</td>
      </tr>`];
    }
  }
  document.getElementById('reason-tbody').innerHTML = rows.join('');
}

function sortAgent(col) {
  if (agentSort.col === col) agentSort.dir *= -1;
  else { agentSort.col = col; agentSort.dir = -1; }
  renderAgentTable();
}

function renderAgentTable() {
  const month = document.getElementById('agent-month').value;
  const search = (document.getElementById('agent-search').value || '').toLowerCase();

  // Aggregate data
  let data = [];
  if (month === 'all') {
    const byAgent = {};
    DATA.monthly_by_agent.forEach(row => {
      const k = row.agent_id;
      if (!byAgent[k]) byAgent[k] = {...row, refund_count: 0, refund_amount: 0, gw_other_count: 0};
      byAgent[k].refund_count += row.refund_count;
      byAgent[k].refund_amount += row.refund_amount;
      byAgent[k].gw_other_count += row.gw_other_count;
    });
    data = Object.values(byAgent).map(r => ({...r, gw_other_rate_pct: r.refund_count ? +(r.gw_other_count / r.refund_count * 100).toFixed(1) : 0}));
  } else {
    data = DATA.monthly_by_agent.filter(r => r.month === month);
  }

  if (search) data = data.filter(r => (r.agent_name+r.team+r.site).toLowerCase().includes(search));

  data.sort((a,b) => agentSort.dir * (a[agentSort.col] > b[agentSort.col] ? 1 : -1));

  const maxAmt = Math.max(...data.map(d => d.refund_amount), 1);

  document.getElementById('agent-tbody').innerHTML = data.length === 0
    ? '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:20px">No data</td></tr>'
    : data.map(row => {
      const gwPct = row.gw_other_rate_pct;
      const gwPill = gwPct > 50 ? 'pill-red' : gwPct > 35 ? 'pill-yellow' : 'pill-green';
      const barW = (row.refund_amount / maxAmt * 100).toFixed(1);
      return `<tr>
        <td class="left">${row.agent_name}</td>
        <td class="left"><span style="font-size:0.78rem;color:var(--muted)">${row.team}</span></td>
        <td>${fmtN(row.refund_count)}</td>
        <td class="amount" style="position:relative">
          <div class="bar-bg" style="width:${barW}%;background:rgba(88,166,255,0.07)"></div>
          <span style="position:relative">${fmt(row.refund_amount)}</span>
        </td>
        <td>${fmtN(row.gw_other_count)}</td>
        <td><span class="pill ${gwPill}">${gwPct}%</span></td>
      </tr>`;
    }).join('');
}

function renderFlags() {
  const gw = DATA.flags.filter(f => f.type === 'GW_OVER_500');
  const dr = DATA.flags.filter(f => f.type === 'DOUBLE_REMEDY');

  // Summarize GW violations by agent
  const gwByAgent = {};
  gw.forEach(f => {
    if (!gwByAgent[f.agent_id]) gwByAgent[f.agent_id] = {name: f.agent_name, count: 0, excess: 0};
    gwByAgent[f.agent_id].count++;
    gwByAgent[f.agent_id].excess += f.excess;
  });

  const drByAgent = {};
  dr.forEach(f => {
    if (!drByAgent[f.agent_id]) drByAgent[f.agent_id] = {name: f.agent_name, count: 0, amount: 0};
    drByAgent[f.agent_id].count++;
    drByAgent[f.agent_id].amount += f.amount;
  });

  const html = `
    <div class="section-title" style="margin-top:0">⚠ Goodwill Over Policy Cap (GW-OTHER > Rs 500)</div>
    <p style="color:var(--muted);font-size:0.83rem;margin-bottom:14px">Policy §5 caps goodwill credits at Rs 500/ticket, requiring Team Lead approval. ${gw.length} tickets exceeded this cap.</p>
    ${Object.entries(gwByAgent).sort((a,b) => b[1].excess - a[1].excess).slice(0,15).map(([id, v]) =>
      `<div class="flag-item">
        <div class="icon">🔴</div>
        <div><strong>${v.name}</strong> (${id})<br>
        <div class="meta">${v.count} tickets over cap · Rs ${Math.round(v.excess).toLocaleString('en-IN')} excess paid above Rs 500 ceiling</div>
        </div>
      </div>`
    ).join('')}

    <div class="section-title" style="margin-top:24px">⚠ Double Remedies — Refund + Replacement on Same Order</div>
    <p style="color:var(--muted);font-size:0.83rem;margin-bottom:14px">Policy §5 states: "In no case is a customer to receive both a refund and a replacement for the same order." ${dr.length} tickets flagged.</p>
    ${Object.entries(drByAgent).sort((a,b) => b[1].count - a[1].count).slice(0,15).map(([id, v]) =>
      `<div class="flag-item">
        <div class="icon">🟡</div>
        <div><strong>${v.name}</strong> (${id})<br>
        <div class="meta">${v.count} double-remedy tickets · Rs ${Math.round(v.amount).toLocaleString('en-IN')} refund value</div>
        </div>
      </div>`
    ).join('')}
  `;
  document.getElementById('flags-content').innerHTML = html;
}

function switchTab(tab) {
  ['reason','agent','flags'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('active', t === tab);
    document.getElementById('panel-' + t).classList.toggle('active', t === tab);
  });
}

function showTip(e, html) {
  const t = document.getElementById('tooltip');
  t.innerHTML = html; t.style.display = 'block';
  t.style.left = (e.clientX + 14) + 'px';
  t.style.top = (e.clientY - 20) + 'px';
}
function hideTip() { document.getElementById('tooltip').style.display = 'none'; }
document.addEventListener('mousemove', e => {
  const t = document.getElementById('tooltip');
  if (t.style.display === 'block') { t.style.left = (e.clientX + 14) + 'px'; t.style.top = (e.clientY - 20) + 'px'; }
});

window.onload = init;
</script>
</body>
</html>"""

def generate_html(data):
    import json
    data_json = json.dumps(data, indent=None)
    return HTML_TEMPLATE.replace('__DATA_PLACEHOLDER__', data_json)


def export_csvs(data, out_dir='.'):
    # 1. monthly_by_reason.csv (Pivot format for board pack)
    reason_file = os.path.join(out_dir, 'monthly_refunds_by_reason.csv')
    reasons = data.get('all_reasons', [])
    with open(reason_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        header = ['Month', 'Total Refund INR']
        for r in reasons:
            header.extend([f'{r} Count', f'{r} Amount INR'])
        writer.writerow(header)
        for row in data['monthly_by_reason']:
            line = [row['month'], row['total_amount']]
            for r in reasons:
                line.extend([row.get(f'{r}_count', 0), row.get(f'{r}_amount', 0.0)])
            writer.writerow(line)

    # 2. monthly_by_agent.csv
    agent_file = os.path.join(out_dir, 'monthly_refunds_by_agent.csv')
    with open(agent_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Month', 'Agent ID', 'Agent Name', 'Team', 'Site', 'Refund Count', 'Total Refund INR', 'GW-OTHER Count', 'GW-OTHER Rate Pct'])
        for a in data['monthly_by_agent']:
            writer.writerow([a['month'], a['agent_id'], a['agent_name'], a['team'], a['site'], a['refund_count'], a['refund_amount'], a['gw_other_count'], a['gw_other_rate_pct']])

    # 3. policy_violations.csv
    flags_file = os.path.join(out_dir, 'policy_violations.csv')
    with open(flags_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Violation Type', 'Ticket ID', 'Month', 'Agent ID', 'Agent Name', 'Amount INR', 'Excess INR'])
        for fl in data['flags']:
            writer.writerow([fl.get('type'), fl.get('ticket_id'), fl.get('month'), fl.get('agent_id'), fl.get('agent_name'), fl.get('amount'), fl.get('excess', 0)])

    print(f"[OK] Exported CSV summaries:\n     - {reason_file}\n     - {agent_file}\n     - {flags_file}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Vireo Audio Refund Analysis Tool')
    parser.add_argument('--data-dir', default='.', help='Directory containing CSV files')
    parser.add_argument('--output', default='refund_dashboard.html', help='Output HTML file')
    parser.add_argument('--export-csv', action='store_true', help='Export CSV tables for board pack')
    parser.add_argument('--serve', action='store_true', help='Serve in browser after generating')
    args = parser.parse_args()

    print('Vireo Audio Refund Analysis Tool')
    print('=' * 40)
    print(f'Loading data from: {os.path.abspath(args.data_dir)}')

    data = process_data(args.data_dir)

    s = data['summary']
    print(f"\n[OK] Loaded {s['totals']['clean_ticket_count']} deduplicated tickets")
    print(f"[OK] {s['totals']['refund_ticket_count']} refund tickets | Total: Rs {s['totals']['total_refund_inr']:,.0f}")
    print(f"[OK] {s['flags']['gw_over_500_count']} GW-OTHER > Rs 500 violations (Rs {s['flags']['gw_over_500_excess_inr']:,.0f} excess)")
    print(f"[OK] {s['flags']['double_remedy_count']} double-remedy tickets")

    html = generate_html(data)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n[OK] Dashboard written to: {os.path.abspath(args.output)}")

    if args.export_csv:
        export_csvs(data, args.data_dir)

    if args.serve:
        import webbrowser
        webbrowser.open(f'file://{os.path.abspath(args.output)}')
        print('  Opened in browser.')

    print('\nDone.')


if __name__ == '__main__':
    main()
