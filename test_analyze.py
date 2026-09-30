"""
Unit tests for Vireo Audio Refund Analysis Tool (analyze.py)
Run with: python -m unittest test_analyze.py
"""

import os
import unittest
import analyze

class TestRefundAnalysis(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data_dir = os.path.dirname(os.path.abspath(__file__))
        cls.data = analyze.process_data(cls.data_dir)

    def test_deduplication_count(self):
        """Verify 12,238 raw rows deduplicate to 11,600 unique tickets (638 duplicates)."""
        raw_tickets = analyze.load_csv(os.path.join(self.data_dir, 'tickets.csv'))
        self.assertEqual(len(raw_tickets), 12238)
        clean_count = self.data['summary']['totals']['clean_ticket_count']
        self.assertEqual(clean_count, 11600)
        self.assertEqual(len(raw_tickets) - clean_count, 638)

    def test_legacy_fd_normalization(self):
        """Verify legacy_fd amounts are divided by 100 (paise to rupees conversion)."""
        raw_tickets = analyze.load_csv(os.path.join(self.data_dir, 'tickets.csv'))
        # Find TK-240003 which exists in both helpdesk and legacy_fd
        tk_legacy = next((t for t in raw_tickets if t['ticket_id'] == 'TK-240003' and t.get('source_system') == 'legacy_fd'), None)
        tk_helpdesk = next((t for t in raw_tickets if t['ticket_id'] == 'TK-240003' and t.get('source_system') == 'helpdesk'), None)

        self.assertIsNotNone(tk_legacy)
        self.assertIsNotNone(tk_helpdesk)
        self.assertEqual(float(tk_legacy['refund_amount_inr']), 90000.0)
        self.assertEqual(float(tk_helpdesk['refund_amount_inr']), 900.0)
        self.assertEqual(float(tk_legacy['refund_amount_inr']) / 100.0, float(tk_helpdesk['refund_amount_inr']))

    def test_reconciled_totals(self):
        """Verify the total refund amount matches ~Rs 67.1 lakh."""
        total_refund = self.data['summary']['totals']['total_refund_inr']
        self.assertEqual(total_refund, 6709932.0)
        self.assertEqual(self.data['summary']['totals']['refund_ticket_count'], 2340)

    def test_policy_violations_flags(self):
        """Verify the count and excess of GW-OTHER > Rs 500 and double remedies."""
        flags_summary = self.data['summary']['flags']
        self.assertEqual(flags_summary['gw_over_500_count'], 879)
        self.assertEqual(flags_summary['gw_over_500_excess_inr'], 2432132.0)
        self.assertEqual(flags_summary['double_remedy_count'], 166)

    def test_dashboard_generation(self):
        """Verify HTML dashboard is self-contained and placeholder is populated."""
        html = analyze.generate_html(self.data)
        self.assertNotIn('__DATA_PLACEHOLDER__', html)
        self.assertIn('Vireo Audio — Refund Summary', html)
        self.assertIn('6709932', html)

    def test_csv_export(self):
        """Verify CSV export functionality."""
        analyze.export_csvs(self.data, self.data_dir)
        reason_csv = os.path.join(self.data_dir, 'monthly_refunds_by_reason.csv')
        agent_csv = os.path.join(self.data_dir, 'monthly_refunds_by_agent.csv')
        flags_csv = os.path.join(self.data_dir, 'policy_violations.csv')

        self.assertTrue(os.path.exists(reason_csv))
        self.assertTrue(os.path.exists(agent_csv))
        self.assertTrue(os.path.exists(flags_csv))


if __name__ == '__main__':
    unittest.main()
