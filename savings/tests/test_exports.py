"""
savings/tests/test_exports.py

Verifies the Excel exports produce valid workbooks with the right
columns, row counts, and numbers matching reporting.py.
"""

from decimal import Decimal
from datetime import date
from savings.infrastructure import execute_withdrawal

from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from openpyxl import load_workbook
from io import BytesIO

from authentication.models import MemberProfile, Collector
from savings.models import SavingsCycle, SavingsEntry, Withdrawal
from savings.exports import (
    build_cycle_export,
    build_member_history_export,
    build_collector_export,
    build_all_collectors_export,
)

User = get_user_model()
from django.test import override_settings

@override_settings(DEBUG_PROPAGATE_EXCEPTIONS=True)

    


class ExportTestBase(TestCase):
    """Common fixtures: one collector, two members, one cycle, some entries."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='admin', email='admin@test.local', password='pass123', is_staff=True
        )

        self.collector = Collector.objects.create(name='Test Collector')

        self.member1 = self._make_member('M001', 'Alice', 'Amoding')
        self.member2 = self._make_member('M002', 'Brian', 'Byaruhanga')

        self.cycle = SavingsCycle.objects.create(
            name='August 2026',
            start_date=date(2026, 8, 1),
            status='active',
        )

        SavingsEntry.objects.create(
            member=self.member1, cycle=self.cycle,
            amount=Decimal('50000.00'), date=date(2026, 8, 5),
            created_by=self.user,
        )
        SavingsEntry.objects.create(
            member=self.member1, cycle=self.cycle,
            amount=Decimal('30000.00'), date=date(2026, 8, 12),
            created_by=self.user,
        )
        SavingsEntry.objects.create(
            member=self.member2, cycle=self.cycle,
            amount=Decimal('20000.00'), date=date(2026, 8, 8),
            created_by=self.user,
        )
        execute_withdrawal(
            member_id=self.member1.id,
            cycle=self.cycle,
            amount=Decimal('10000.00'),
            date=date(2026, 8, 20),
            reason='test withdrawal',
            created_by=self.user,
        )

    def _make_member(self, membership_id, first_name, last_name):
        # NOTE: User.email is unique=True. create_user() defaults a
        # missing email to '' (empty string), and MySQL (unlike SQLite)
        # enforces uniqueness on '' too — so every test user needs its
        # own explicit email or the second member creation blows up with
        # "Duplicate entry '' for key 'users.email'".
        u = User.objects.create_user(
            username=membership_id.lower(),
            email=f'{membership_id.lower()}@test.local',
            password='pass123',
            first_name=first_name,
            last_name=last_name,
        )
        return MemberProfile.objects.create(
            user=u,
            membership_id=membership_id,
            collector=self.collector,
            is_active_member=True,
        )

    @staticmethod
    def _load(buf):
        buf.seek(0)
        return load_workbook(BytesIO(buf.read()))


class CycleExportBuilderTests(ExportTestBase):

    def test_produces_valid_workbook(self):
        members = MemberProfile.objects.filter(is_active_member=True)
        buf = build_cycle_export(self.cycle, members)
        wb = self._load(buf)
        self.assertIn(wb.active.title, self.cycle.name)

    def test_header_row_has_expected_columns(self):
        members = MemberProfile.objects.filter(is_active_member=True)
        buf = build_cycle_export(self.cycle, members)
        wb = self._load(buf)
        ws = wb.active
        headers = [c.value for c in ws[3]]  # header row is row 3 (row 1 = title)
        self.assertEqual(headers, [
            'Membership ID', 'Member Name', 'Carry Forward', 'Savings',
            'Withdrawals', 'Closing Balance', 'Returned Amount',
        ])

    def test_row_count_matches_member_count(self):
        members = MemberProfile.objects.filter(is_active_member=True)
        buf = build_cycle_export(self.cycle, members)
        wb = self._load(buf)
        ws = wb.active
        # rows: 1 title, 2 blank, 3 header, then N member rows, then 1 totals row
        data_rows = ws.max_row - 3 - 1  # minus header block, minus totals row
        self.assertEqual(data_rows, members.count())

    def test_amounts_match_reporting(self):
        members = MemberProfile.objects.filter(is_active_member=True).order_by('membership_id')
        buf = build_cycle_export(self.cycle, members)
        wb = self._load(buf)
        ws = wb.active

        rows_by_membership_id = {}
        for row in ws.iter_rows(min_row=4, max_row=ws.max_row - 1, values_only=True):
            if row[0]:
                rows_by_membership_id[row[0]] = row

        # Alice: 50000 + 30000 saved, 10000 withdrawn -> 70000 closing
        alice_row = rows_by_membership_id['M001']
        self.assertEqual(Decimal(str(alice_row[3])), Decimal('80000.00'))  # savings
        self.assertEqual(Decimal(str(alice_row[4])), Decimal('10000.00'))  # withdrawals
        self.assertEqual(Decimal(str(alice_row[5])), Decimal('70000.00'))  # closing balance

        # Brian: 20000 saved, 0 withdrawn -> 20000 closing
        brian_row = rows_by_membership_id['M002']
        self.assertEqual(Decimal(str(brian_row[3])), Decimal('20000.00'))
        self.assertEqual(Decimal(str(brian_row[4])), Decimal('0.00'))
        self.assertEqual(Decimal(str(brian_row[5])), Decimal('20000.00'))

    def test_totals_row_sums_correctly(self):
        members = MemberProfile.objects.filter(is_active_member=True)
        buf = build_cycle_export(self.cycle, members)
        wb = self._load(buf)
        ws = wb.active
        last_row = [c.value for c in ws[ws.max_row]]
        self.assertEqual(last_row[1], 'TOTAL')
        self.assertEqual(Decimal(str(last_row[3])), Decimal('100000.00'))  # total savings
        self.assertEqual(Decimal(str(last_row[4])), Decimal('10000.00'))   # total withdrawals
        self.assertEqual(Decimal(str(last_row[5])), Decimal('90000.00'))   # total closing balance


class MemberHistoryExportBuilderTests(ExportTestBase):

    def test_produces_valid_workbook_with_one_row_per_cycle(self):
        buf = build_member_history_export(self.member1)
        wb = self._load(buf)
        ws = wb.active
        headers = [c.value for c in ws[3]]
        self.assertEqual(headers, [
            'Cycle', 'Carry Forward', 'Savings', 'Withdrawals',
            'Closing Balance', 'Returned Amount',
        ])
        data_rows = [r for r in ws.iter_rows(min_row=4, values_only=True) if r[0]]
        self.assertEqual(len(data_rows), 1)  # member1 only has activity in one cycle
        self.assertEqual(data_rows[0][0], self.cycle.name)


class CollectorExportBuilderTests(ExportTestBase):

    def test_single_collector_export(self):
        members = MemberProfile.objects.filter(collector=self.collector)
        buf = build_collector_export(self.collector, members, cycle=self.cycle)
        wb = self._load(buf)
        ws = wb.active
        row = [c.value for c in ws[2]]
        self.assertEqual(row[1], 2)  # member_count
        self.assertEqual(Decimal(str(row[2])), Decimal('100000.00'))  # total_savings
        self.assertEqual(Decimal(str(row[3])), Decimal('10000.00'))   # total_withdrawals

    def test_all_collectors_export(self):
        collectors_with_members = [
            (self.collector, MemberProfile.objects.filter(collector=self.collector))
        ]
        buf = build_all_collectors_export(collectors_with_members, cycle=self.cycle)
        wb = self._load(buf)
        ws = wb.active
        data_rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]
        self.assertEqual(len(data_rows), 1)


class ExportEndpointSmokeTests(ExportTestBase):
    """One request per endpoint, checking status code and that the
    response actually looks like an xlsx file — not re-testing the
    numbers, since the builder tests above already cover that."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _assert_is_xlsx(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        self.assertTrue(response.content.startswith(b'PK'))  # xlsx = zip container

    def test_cycle_export_defaults_to_active_cycle(self):
        response = self.client.get('/api/savings/export/cycle/')
        self._assert_is_xlsx(response)

    def test_cycle_export_with_explicit_cycle_id(self):
        response = self.client.get(f'/api/savings/export/cycle/?cycle_id={self.cycle.id}')
        self._assert_is_xlsx(response)

    def test_cycle_export_404s_on_bad_cycle_id(self):
        response = self.client.get('/api/savings/export/cycle/?cycle_id=99999')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_member_history_export(self):
        response = self.client.get(f'/api/savings/export/member/{self.member1.id}/')
        self._assert_is_xlsx(response)

    def test_member_history_export_404s_on_bad_member_id(self):
        response = self.client.get('/api/savings/export/member/99999/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_collector_export(self):
        response = self.client.get(f'/api/savings/export/collector/{self.collector.id}/')
        self._assert_is_xlsx(response)

    def test_collector_export_with_cycle_filter(self):
        response = self.client.get(
            f'/api/savings/export/collector/{self.collector.id}/?cycle_id={self.cycle.id}'
        )
        self._assert_is_xlsx(response)

    def test_all_collectors_export(self):
        response = self.client.get('/api/savings/export/collectors/')
        self._assert_is_xlsx(response)

    def test_exports_require_auth(self):
        anon_client = APIClient()
        response = anon_client.get('/api/savings/export/cycle/')
        self.assertIn(response.status_code, (401, 403))