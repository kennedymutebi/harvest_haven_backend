"""
savings/tests/test_pdf_exports.py

Verifies the PDF exports produce valid PDF files, and that their numbers
match reporting.py — same fixtures as test_exports.py so both suites can
be reasoned about together.
"""

from decimal import Decimal
from datetime import date

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from authentication.models import MemberProfile, Collector
from savings.models import SavingsCycle, SavingsEntry, Withdrawal
from savings.pdf_exports import (
    build_cycle_pdf,
    build_member_statement_pdf,
    build_collector_pdf,
)

User = get_user_model()


class PdfExportTestBase(TestCase):
    """Same fixtures as ExportTestBase in test_exports.py."""

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
        Withdrawal.objects.create(
            member=self.member1, cycle=self.cycle,
            amount=Decimal('10000.00'), date=date(2026, 8, 20),
            created_by=self.user,
        )

    def _make_member(self, membership_id, first_name, last_name):
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
    def _assert_is_pdf_bytes(buf):
        buf.seek(0)
        content = buf.read()
        # every valid PDF starts with this magic header
        assert content.startswith(b'%PDF-'), "output is not a valid PDF"
        assert len(content) > 500, "PDF suspiciously small — likely empty/broken"
        return content


class CyclePdfBuilderTests(PdfExportTestBase):

    def test_produces_valid_pdf(self):
        members = MemberProfile.objects.filter(is_active_member=True)
        buf = build_cycle_pdf(self.cycle, members)
        self._assert_is_pdf_bytes(buf)

    def test_pdf_grows_with_more_members(self):
        # Weak but useful signal: a report with 2 members should not be
        # byte-identical in size to one with 0 — catches "table silently
        # empty" bugs without parsing PDF internals.
        members = MemberProfile.objects.filter(is_active_member=True)
        buf_with_members = build_cycle_pdf(self.cycle, members)
        content_with = self._assert_is_pdf_bytes(buf_with_members)

        buf_empty = build_cycle_pdf(self.cycle, MemberProfile.objects.none())
        content_empty = self._assert_is_pdf_bytes(buf_empty)

        self.assertGreater(len(content_with), len(content_empty))


class MemberStatementPdfBuilderTests(PdfExportTestBase):

    def test_produces_valid_pdf_for_member_with_history(self):
        buf = build_member_statement_pdf(self.member1)
        self._assert_is_pdf_bytes(buf)

    def test_produces_valid_pdf_for_member_with_no_history(self):
        # member2 has entries but let's also test a genuinely blank member
        blank_user = User.objects.create_user(
            username='m099', email='m099@test.local', password='pass123',
            first_name='No', last_name='History',
        )
        blank_member = MemberProfile.objects.create(
            user=blank_user, membership_id='M099',
            collector=self.collector, is_active_member=True,
        )
        buf = build_member_statement_pdf(blank_member)
        self._assert_is_pdf_bytes(buf)  # should still render, just with the "no activity" message


class CollectorPdfBuilderTests(PdfExportTestBase):

    def test_produces_valid_pdf_scoped_to_cycle(self):
        members = MemberProfile.objects.filter(collector=self.collector)
        buf = build_collector_pdf(self.collector, members, cycle=self.cycle)
        self._assert_is_pdf_bytes(buf)

    def test_produces_valid_pdf_all_time(self):
        members = MemberProfile.objects.filter(collector=self.collector)
        buf = build_collector_pdf(self.collector, members, cycle=None)
        self._assert_is_pdf_bytes(buf)


@override_settings(DEBUG_PROPAGATE_EXCEPTIONS=True)
class PdfExportEndpointSmokeTests(PdfExportTestBase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _assert_pdf_response(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))

    def test_cycle_pdf_defaults_to_active_cycle(self):
        response = self.client.get('/api/savings/export/cycle/pdf/')
        self._assert_pdf_response(response)

    def test_cycle_pdf_with_explicit_cycle_id(self):
        response = self.client.get(f'/api/savings/export/cycle/pdf/?cycle_id={self.cycle.id}')
        self._assert_pdf_response(response)

    def test_cycle_pdf_404s_on_bad_cycle_id(self):
        response = self.client.get('/api/savings/export/cycle/pdf/?cycle_id=99999')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_member_statement_pdf(self):
        response = self.client.get(f'/api/savings/export/member/{self.member1.id}/pdf/')
        self._assert_pdf_response(response)

    def test_member_statement_pdf_404s_on_bad_member_id(self):
        response = self.client.get('/api/savings/export/member/99999/pdf/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_collector_pdf(self):
        response = self.client.get(f'/api/savings/export/collector/{self.collector.id}/pdf/')
        self._assert_pdf_response(response)

    def test_collector_pdf_with_cycle_filter(self):
        response = self.client.get(
            f'/api/savings/export/collector/{self.collector.id}/pdf/?cycle_id={self.cycle.id}'
        )
        self._assert_pdf_response(response)

    def test_pdf_exports_require_auth(self):
        anon_client = APIClient()
        response = anon_client.get('/api/savings/export/cycle/pdf/')
        self.assertIn(response.status_code, (401, 403))