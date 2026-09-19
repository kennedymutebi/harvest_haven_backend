"""
savings/tests/test_api_endpoints.py

REGRESSION tests for the savings app's actual HTTP endpoints - the layer
above test_infrastructure.py. Each test here hits a real URL through
Django's test client (via DRF's APIClient), exactly like your frontend
or Postman would, and checks the status code + response shape.

Purpose: catch a broken URL, a missing permission, a serializer field
rename, or a view returning the wrong status code - things the domain
and infrastructure tests CANNOT catch, because those never touch urls.py
or a real HTTP request/response cycle.

This is the layer to run in CI on every push/PR. It's slower than the
domain tests (needs a real database) but still fast enough for CI -
these run in well under a second per test.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from authentication.models import User, MemberProfile, Collector
from savings.models import SavingsCycle, SavingsEntry, Withdrawal


class SavingsEndpointTestCase(TestCase):
    """Shared setup for all endpoint tests: one authenticated admin user,
    one member with a two-cycle history (old money + this month's money),
    so every test starts from a realistic, non-trivial state."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(username='admin', email='admin@test.com', password='pass12345')
        self.client.force_authenticate(user=self.admin)

        member_user = User.objects.create_user(
            username='member1', email='member1@test.com', password='pass12345',
            first_name='Alice', last_name='N'

        )
        self.member = MemberProfile.objects.create(
            user=member_user, membership_id='MEM001', registered_by=self.admin
        )

        self.july = SavingsCycle.objects.create(
            name='July 2026', start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31), status='closed',
        )
        self.august = SavingsCycle.objects.create(
            name='August 2026', start_date=date(2026, 8, 1), status='active',
        )
        SavingsEntry.objects.create(
            member=self.member, cycle=self.july, amount=Decimal('120000'), date=date(2026, 7, 10),
        )
        SavingsEntry.objects.create(
            member=self.member, cycle=self.august, amount=Decimal('14000'), date=date(2026, 8, 5),
        )


class UnauthenticatedAccessTest(TestCase):
    """Every endpoint must reject anonymous requests - this is a security
    regression test, not a business-logic one."""

    def setUp(self):
        self.client = APIClient()  # deliberately NOT authenticated

    def test_cycles_list_requires_auth(self):
        resp = self.client.get('/api/cycles/')
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_withdrawal_create_requires_auth(self):
        resp = self.client.post('/api/savings/withdrawals/', {'member': 1, 'amount': '1000', 'date': '2026-08-01'})
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_profit_endpoint_requires_auth(self):
        resp = self.client.get('/api/savings/profit/')
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class CycleEndpointsTest(SavingsEndpointTestCase):
    def test_list_cycles(self):
        resp = self.client.get('/api/cycles/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

    def test_get_active_cycle(self):
        resp = self.client.get('/api/cycles/active/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'August 2026')

    def test_create_cycle(self):
        resp = self.client.post('/api/cycles/', {'start_date': '2026-09-01', 'status': 'upcoming'})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'September 2026')  # auto-generated name

    def test_cycle_total_profit_uses_tiered_calculation_not_percentage(self):
        # Regression guard for the exact swap we made: this MUST stay
        # 7000 (tiered), never drift back to 46000 (18.4% of 250000).
        SavingsEntry.objects.create(
            member=self.member, cycle=self.august, amount=Decimal('236000'), date=date(2026, 8, 12)
        )  # brings August total for this member to 250,000
        resp = self.client.get(f'/api/cycles/{self.august.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_profit'], 7000.0)

    def test_close_cycle(self):
        resp = self.client.post(f'/api/cycles/{self.august.id}/close/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.august.refresh_from_db()
        self.assertEqual(self.august.status, 'closed')

    def test_cannot_close_already_closed_cycle(self):
        resp = self.client.post(f'/api/cycles/{self.july.id}/close/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cycle_statistics(self):
        resp = self.client.get('/api/cycles/statistics/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['closed'], 1)
        self.assertEqual(resp.data['active'], 1)


class SavingsEntryEndpointsTest(SavingsEndpointTestCase):
    def test_list_entries(self):
        resp = self.client.get('/api/savings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

    def test_create_entry_goes_to_active_cycle(self):
        resp = self.client.post('/api/savings/', {
            'member': self.member.id, 'amount': '5000', 'date': '2026-08-20',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['cycle'], self.august.id)

    def test_late_entry_into_closed_cycle(self):
        resp = self.client.post('/api/savings/late-entry/', {
            'member': self.member.id, 'amount': '3000', 'date': '2026-07-15', 'cycle': self.july.id,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['is_late_entry'])

    def test_late_entry_rejects_active_cycle(self):
        resp = self.client.post('/api/savings/late-entry/', {
            'member': self.member.id, 'amount': '3000', 'date': '2026-08-15', 'cycle': self.august.id,
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_entry_blocked_after_withdrawal_drew_from_it(self):
        entry = SavingsEntry.objects.get(cycle=self.july)
        self.client.post('/api/savings/withdrawals/', {
            'member': self.member.id, 'amount': '50000', 'date': '2026-08-15',
        })
        resp = self.client.delete(f'/api/savings/{entry.id}/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class WithdrawalEndpointsTest(SavingsEndpointTestCase):
    def test_withdrawal_from_lifetime_pool_succeeds(self):
        # 100,000 > August's own 14,000, but within the 134,000 lifetime
        # pool - this is the core regression guard for the B/F fix.
        resp = self.client.post('/api/savings/withdrawals/', {
            'member': self.member.id, 'amount': '100000', 'date': '2026-08-15', 'reason': 'test',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(resp.data['allocations']), 1)
        self.assertEqual(resp.data['allocations'][0]['deposit_date'], '2026-07-10')

    def test_withdrawal_overdraw_rejected(self):
        resp = self.client.post('/api/savings/withdrawals/', {
            'member': self.member.id, 'amount': '999999', 'date': '2026-08-15',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_active_cycle_rejects_withdrawal(self):
        self.august.status = 'closed'
        self.august.save()
        resp = self.client.post('/api/savings/withdrawals/', {
            'member': self.member.id, 'amount': '1000', 'date': '2026-08-15',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_withdrawals(self):
        self.client.post('/api/savings/withdrawals/', {
            'member': self.member.id, 'amount': '5000', 'date': '2026-08-15',
        })
        resp = self.client.get('/api/savings/withdrawals/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)


class MemberBalanceEndpointsTest(SavingsEndpointTestCase):
    def test_member_detail_returns_correct_brought_forward(self):
        # Direct regression guard for Section 3's own worked example.
        resp = self.client.get(f'/api/savings/view-savings/members/{self.member.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['carry_forward'], 120000.0)
        self.assertEqual(resp.data['net_balance'], 134000.0)

    def test_member_history_lists_both_cycles(self):
        resp = self.client.get(f'/api/savings/view-savings/members/{self.member.id}/history/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_cycles'], 2)

    def test_unknown_member_returns_404(self):
        resp = self.client.get('/api/savings/view-savings/members/99999/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class ProfitEndpointsTest(SavingsEndpointTestCase):
    def test_member_profit_matches_section_7_example(self):
        SavingsEntry.objects.create(
            member=self.member, cycle=self.august, amount=Decimal('236000'), date=date(2026, 8, 12)
        )  # August total now 250,000
        resp = self.client.get(f'/api/savings/members/{self.member.id}/profit/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['charge'], 7000.0)

    def test_profit_unaffected_by_same_month_withdrawal(self):
        SavingsEntry.objects.create(
            member=self.member, cycle=self.august, amount=Decimal('236000'), date=date(2026, 8, 12)
        )
        self.client.post('/api/savings/withdrawals/', {
            'member': self.member.id, 'amount': '200000', 'date': '2026-08-20',
        })
        resp = self.client.get(f'/api/savings/members/{self.member.id}/profit/')
        self.assertEqual(resp.data['charge'], 7000.0)  # unchanged

    def test_cycle_profit_lists_all_members(self):
        second_member_user = User.objects.create_user(username='member2', password='pass12345')
        second_member = MemberProfile.objects.create(user=second_member_user, membership_id='MEM002')
        SavingsEntry.objects.create(
            member=second_member, cycle=self.august, amount=Decimal('40000'), date=date(2026, 8, 5)
        )
        resp = self.client.get('/api/savings/profit/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['members_charged'], 2)


class CollectorAndSearchEndpointsTest(SavingsEndpointTestCase):
    def test_collector_summary(self):
        collector = Collector.objects.create(name='Team A')
        self.member.collector = collector
        self.member.save()
        resp = self.client.get(f'/api/savings/collectors/{collector.id}/summary/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['members_count'], 1)

    def test_member_search_by_name(self):
        resp = self.client.get('/api/savings/members/search/?q=Alice')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 1)

    def test_member_search_no_results(self):
        resp = self.client.get('/api/savings/members/search/?q=NoSuchPerson')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 0)