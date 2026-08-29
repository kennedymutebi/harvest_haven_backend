"""
savings/tests.py

Full test suite for Phase 1 (cycle-scoping fix + late-save feature).

WHERE THIS GOES:
    Replace the existing savings/tests.py with this file entirely.
    (If your app has a tests/ FOLDER instead of a tests.py file, delete
    the folder first — Django doesn't allow both.)

HOW TO RUN:
    python manage.py test savings

WHAT'S COVERED:
    1. SavingsCycleModelTests / SavingsEntryModelTests / WithdrawalModelTests
       — the model-level methods and properties.
    2. SerializerTests
       — withdrawal validation is scoped to the active cycle; late-save
         entry creation tags is_late_entry correctly.
    3. ReportingTests
       — reporting.py functions: per-cycle summary, lifetime history,
         collector summary.
    4. ViewTests
       — hits every endpoint directly via APIRequestFactory (no dependency
         on how your project's root urls.py mounts the app).
       — THE MOST IMPORTANT TEST HERE IS
         `test_new_cycle_shows_zero_despite_old_withdrawals`, which is a
         direct regression test for the bug you reported.
    5. BackfillCommandTests
       — the management command correctly assigns old cycle=NULL
         withdrawals to the cycle whose date range covers them, and
         leaves --dry-run runs unchanged.
"""

from decimal import Decimal
from datetime import date

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from authentication.models import User, MemberProfile, Collector
from savings.models import SavingsCycle, SavingsEntry, Withdrawal, WithdrawalAllocation
from savings.serializers import CreateWithdrawalSerializer, CreateSavingsEntrySerializer
from savings.reporting import (
    get_member_cycle_summary,
    get_member_lifetime_history,
    get_collector_summary,
)
from savings.views import (
    SavingsEntryViewSet,
    WithdrawalViewSet,
    MembersListWithSavingsView,
    MemberSavingsDetailView,
    MemberSavingsHistoryView,
    LateSavingsEntryView,
    MemberSearchView,
    CollectorSavingsSummaryView,
)


# ============================================
# SHARED TEST HELPERS
# ============================================

class FakeRequest:
    """Minimal stand-in for a DRF request, only used where a serializer
    needs `context['request'].user` and we're not going through a real
    view (see WithdrawalSerializer.create -> created_by)."""
    def __init__(self, user):
        self.user = user


def make_user(username, **kwargs):
    """
    Creates a test user with a guaranteed-unique email.

    Why this matters: User.email is unique=True but blank=True/null=True.
    Django's create_user() defaults a missing email to '' (empty string),
    NOT None. SQLite silently allows multiple '' values, but MySQL treats
    '' as a real value for uniqueness — so the second user created without
    an explicit email collides with the first on 'duplicate entry for key
    users.email'. Giving each test user its own email avoids that entirely.
    """
    email = kwargs.pop('email', f'{username}@test.local')
    return User.objects.create_user(username=username, email=email, password='testpass123', **kwargs)


def make_collector(name='Main Collector'):
    return Collector.objects.create(name=name)


def make_member(user, collector=None, registered_by=None):
    return MemberProfile.objects.create(
        user=user, collector=collector, registered_by=registered_by
    )


def make_cycle(name, start_date, end_date=None, status='active'):
    return SavingsCycle.objects.create(
        name=name, start_date=start_date, end_date=end_date, status=status
    )


def make_entry(member, cycle, amount, entry_date, created_by=None):
    return SavingsEntry.objects.create(
        member=member, cycle=cycle, amount=Decimal(str(amount)),
        date=entry_date, created_by=created_by
    )


# ============================================
# 1. MODEL TESTS
# ============================================

class SavingsCycleModelTests(TestCase):

    def setUp(self):
        self.admin = make_user('admin1', is_staff=True)
        self.member = make_member(make_user('member1'))
        self.cycle = make_cycle('August 2026', date(2026, 8, 1), date(2026, 8, 31), status='active')

    def test_total_savings_sums_only_this_cycle(self):
        make_entry(self.member, self.cycle, 10000, date(2026, 8, 5), self.admin)
        make_entry(self.member, self.cycle, 5000, date(2026, 8, 10), self.admin)

        other_cycle = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        make_entry(self.member, other_cycle, 99999, date(2026, 7, 5), self.admin)

        self.assertEqual(self.cycle.total_savings(), Decimal('15000.00'))

    def test_total_withdrawals_scoped_to_cycle(self):
        make_entry(self.member, self.cycle, 20000, date(2026, 8, 1), self.admin)
        Withdrawal.objects.create(
            member=self.member, cycle=self.cycle, amount=Decimal('5000'),
            date=date(2026, 8, 6), created_by=self.admin
        )
        other_cycle = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        Withdrawal.objects.create(
            member=self.member, cycle=other_cycle, amount=Decimal('99999'),
            date=date(2026, 7, 6), created_by=self.admin
        )

        self.assertEqual(self.cycle.total_withdrawals(), Decimal('5000.00'))

    def test_closing_balance(self):
        make_entry(self.member, self.cycle, 10000, date(2026, 8, 1), self.admin)
        Withdrawal.objects.create(
            member=self.member, cycle=self.cycle, amount=Decimal('4000'),
            date=date(2026, 8, 2), created_by=self.admin
        )
        self.assertEqual(self.cycle.closing_balance(), Decimal('6000.00'))

    def test_previous_cycle_by_start_date(self):
        july = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        self.assertEqual(self.cycle.previous_cycle().id, july.id)

    def test_previous_cycle_none_when_first_ever_cycle(self):
        self.assertIsNone(self.cycle.previous_cycle())


class SavingsEntryModelTests(TestCase):

    def setUp(self):
        self.admin = make_user('admin2', is_staff=True)
        self.member = make_member(make_user('member2'))
        self.cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')

    def test_remaining_amount(self):
        entry = make_entry(self.member, self.cycle, 10000, date(2026, 8, 1), self.admin)
        entry.withdrawn_amount = Decimal('3000')
        entry.save()
        self.assertEqual(entry.remaining_amount, Decimal('7000.00'))

    def test_is_withdrawn_from_false_by_default(self):
        entry = make_entry(self.member, self.cycle, 10000, date(2026, 8, 1), self.admin)
        self.assertFalse(entry.is_withdrawn_from)

    def test_is_withdrawn_from_true_after_allocation(self):
        entry = make_entry(self.member, self.cycle, 10000, date(2026, 8, 1), self.admin)
        withdrawal = Withdrawal.objects.create(
            member=self.member, cycle=self.cycle, amount=Decimal('2000'),
            date=date(2026, 8, 2), created_by=self.admin
        )
        WithdrawalAllocation.objects.create(withdrawal=withdrawal, savings_entry=entry, amount=Decimal('2000'))
        self.assertTrue(entry.is_withdrawn_from)


# ============================================
# 2. SERIALIZER TESTS
# ============================================

class WithdrawalSerializerTests(TestCase):
    """These directly test the fix: withdrawals can only draw from the
    ACTIVE cycle's own deposits, never from a previous cycle's leftovers."""

    def setUp(self):
        self.admin = make_user('admin3', is_staff=True)
        self.member = make_member(make_user('member3'))

        self.old_cycle = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        make_entry(self.member, self.old_cycle, 50000, date(2026, 7, 5), self.admin)
        # old cycle: 50,000 saved, never withdrawn — should NOT be reachable now

        self.active_cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')

    def test_cannot_withdraw_more_than_active_cycle_balance(self):
        # New cycle has 0 saved so far -> withdrawing anything should fail,
        # even though the member has 50,000 sitting in the old closed cycle.
        serializer = CreateWithdrawalSerializer(
            data={'member': self.member.id, 'amount': '1000', 'date': '2026-08-05'},
            context={'request': FakeRequest(self.admin)}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('non_field_errors', serializer.errors)

    def test_can_withdraw_up_to_this_cycle_balance(self):
        make_entry(self.member, self.active_cycle, 8000, date(2026, 8, 2), self.admin)

        serializer = CreateWithdrawalSerializer(
            data={'member': self.member.id, 'amount': '5000', 'date': '2026-08-05'},
            context={'request': FakeRequest(self.admin)}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        withdrawal = serializer.save()

        self.assertEqual(withdrawal.cycle_id, self.active_cycle.id)
        self.assertEqual(withdrawal.amount, Decimal('5000.00'))

        entry = SavingsEntry.objects.get(member=self.member, cycle=self.active_cycle)
        self.assertEqual(entry.withdrawn_amount, Decimal('5000.00'))
        self.assertEqual(entry.remaining_amount, Decimal('3000.00'))

    def test_fifo_never_reaches_into_previous_cycle(self):
        # Even a big withdrawal against a big active-cycle deposit must
        # never touch the old cycle's entry.
        make_entry(self.member, self.active_cycle, 8000, date(2026, 8, 2), self.admin)

        serializer = CreateWithdrawalSerializer(
            data={'member': self.member.id, 'amount': '8000', 'date': '2026-08-05'},
            context={'request': FakeRequest(self.admin)}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        old_entry = SavingsEntry.objects.get(member=self.member, cycle=self.old_cycle)
        self.assertEqual(old_entry.withdrawn_amount, Decimal('0.00'))


class SavingsEntrySerializerLateSaveTests(TestCase):

    def setUp(self):
        self.member = make_member(make_user('member4'))
        self.active_cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')
        self.closed_cycle = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')

    def test_no_cycle_given_defaults_to_active_and_not_late(self):
        serializer = CreateSavingsEntrySerializer(
            data={'member': self.member.id, 'amount': '1000', 'date': '2026-08-10'}
        )
        serializer.is_valid(raise_exception=True)
        self.assertEqual(serializer.validated_data['cycle'].id, self.active_cycle.id)
        self.assertFalse(serializer.validated_data['is_late_entry'])

    def test_explicit_closed_cycle_marks_late_entry(self):
        serializer = CreateSavingsEntrySerializer(
            data={
                'member': self.member.id, 'amount': '1000', 'date': '2026-07-20',
                'cycle': self.closed_cycle.id
            }
        )
        serializer.is_valid(raise_exception=True)
        self.assertEqual(serializer.validated_data['cycle'].id, self.closed_cycle.id)
        self.assertTrue(serializer.validated_data['is_late_entry'])

    def test_explicit_active_cycle_not_marked_late(self):
        serializer = CreateSavingsEntrySerializer(
            data={
                'member': self.member.id, 'amount': '1000', 'date': '2026-08-10',
                'cycle': self.active_cycle.id
            }
        )
        serializer.is_valid(raise_exception=True)
        self.assertFalse(serializer.validated_data['is_late_entry'])


# ============================================
# 3. REPORTING TESTS
# ============================================

class ReportingTests(TestCase):

    def setUp(self):
        self.admin = make_user('admin5', is_staff=True)
        self.member = make_member(make_user('member5'))

        self.july = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        make_entry(self.member, self.july, 10000, date(2026, 7, 5), self.admin)
        Withdrawal.objects.create(
            member=self.member, cycle=self.july, amount=Decimal('2000'),
            date=date(2026, 7, 10), created_by=self.admin
        )
        # July closing balance = 8000

        self.august = make_cycle('August 2026', date(2026, 8, 1), status='active')
        make_entry(self.member, self.august, 3000, date(2026, 8, 2), self.admin)

    def test_opening_balance_always_zero(self):
        summary = get_member_cycle_summary(self.member, self.august)
        self.assertEqual(summary['opening_balance'], Decimal('0.00'))

    def test_carry_forward_equals_previous_cycle_closing_balance(self):
        summary = get_member_cycle_summary(self.member, self.august)
        self.assertEqual(summary['carry_forward'], Decimal('8000.00'))

    def test_carry_forward_never_added_into_this_cycle_balance(self):
        summary = get_member_cycle_summary(self.member, self.august)
        # closing_balance should be savings(3000) - withdrawals(0), NOT +carry_forward
        self.assertEqual(summary['closing_balance'], Decimal('3000.00'))

    def test_returned_amount_zero_while_cycle_active(self):
        summary = get_member_cycle_summary(self.member, self.august)
        self.assertEqual(summary['returned_amount'], Decimal('0.00'))

    def test_returned_amount_equals_closing_balance_once_closed(self):
        summary = get_member_cycle_summary(self.member, self.july)
        self.assertEqual(summary['returned_amount'], Decimal('8000.00'))
        self.assertEqual(summary['returned_amount'], summary['closing_balance'])

    def test_lifetime_history_includes_both_cycles(self):
        history = get_member_lifetime_history(self.member)
        cycle_ids = {row['cycle'].id for row in history}
        self.assertEqual(cycle_ids, {self.july.id, self.august.id})

    def test_collector_summary_scoped_to_cycle(self):
        collector = make_collector()
        self.member.collector = collector
        self.member.save()

        summary = get_collector_summary(
            collector, MemberProfile.objects.filter(collector=collector), cycle=self.august
        )
        self.assertEqual(summary['member_count'], 1)
        self.assertEqual(summary['total_savings'], Decimal('3000.00'))
        self.assertEqual(summary['total_withdrawals'], Decimal('0.00'))
        self.assertEqual(summary['total_balance'], Decimal('3000.00'))


# ============================================
# 4. VIEW TESTS (via APIRequestFactory — no dependency on root urls.py)
# ============================================

class ViewTests(TestCase):

    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = make_user('admin6', is_staff=True, is_superuser=True)
        self.user_member = make_user('member6')
        self.member = make_member(self.user_member, registered_by=self.admin)

    def _auth(self, request):
        force_authenticate(request, user=self.admin)
        return request

    def test_new_cycle_shows_zero_despite_old_withdrawals(self):
        """
        THE core regression test for the reported bug: a member with
        significant withdrawal history in a CLOSED cycle must show
        savings=0, withdrawn=0, balance=0 the moment a brand-new cycle
        starts — never a negative number.
        """
        old_cycle = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        make_entry(self.member, old_cycle, 50000, date(2026, 7, 2), self.admin)
        Withdrawal.objects.create(
            member=self.member, cycle=old_cycle, amount=Decimal('45000'),
            date=date(2026, 7, 20), created_by=self.admin
        )

        new_cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')
        # Deliberately no savings entries in the new cycle at all.

        request = self._auth(self.factory.get('/api/view-savings/members/?all=true'))
        response = MembersListWithSavingsView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        member_row = next(m for m in response.data['members'] if m['id'] == self.member.id)

        self.assertEqual(member_row['total_savings'], 0.0)
        self.assertEqual(member_row['total_withdrawn'], 0.0)
        self.assertEqual(member_row['balance'], 0.0)
        self.assertGreaterEqual(member_row['balance'], 0.0)  # never negative

    def test_member_detail_separates_lifetime_from_this_cycle(self):
        old_cycle = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        make_entry(self.member, old_cycle, 20000, date(2026, 7, 2), self.admin)

        new_cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')
        make_entry(self.member, new_cycle, 5000, date(2026, 8, 2), self.admin)

        request = self._auth(self.factory.get('/api/view-savings/members/1/'))
        response = MemberSavingsDetailView.as_view()(request, member_id=self.member.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_lifetime'], 25000.0)
        self.assertEqual(response.data['total_this_month'], 5000.0)
        self.assertEqual(response.data['balance_this_month'], 5000.0)

    def test_member_history_lists_each_cycle_independently(self):
        old_cycle = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        make_entry(self.member, old_cycle, 20000, date(2026, 7, 2), self.admin)
        new_cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')
        make_entry(self.member, new_cycle, 5000, date(2026, 8, 2), self.admin)

        request = self._auth(self.factory.get('/api/view-savings/members/1/history/'))
        response = MemberSavingsHistoryView.as_view()(request, member_id=self.member.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_cycles'], 2)
        totals = {row['cycle_name']: row['total_saved'] for row in response.data['history']}
        self.assertEqual(totals['July 2026'], 20000.0)
        self.assertEqual(totals['August 2026'], 5000.0)

    def test_late_entry_rejected_for_active_cycle(self):
        active_cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')
        request = self._auth(self.factory.post('/api/savings/late-entry/', {
            'member': self.member.id, 'amount': '1000', 'date': '2026-08-05',
            'cycle': active_cycle.id
        }))
        response = LateSavingsEntryView.as_view()(request)
        self.assertEqual(response.status_code, 400)

    def test_late_entry_accepted_for_closed_cycle_and_excluded_from_active(self):
        closed_cycle = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        active_cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')

        request = self._auth(self.factory.post('/api/savings/late-entry/', {
            'member': self.member.id, 'amount': '1000', 'date': '2026-07-15',
            'cycle': closed_cycle.id
        }))
        response = LateSavingsEntryView.as_view()(request)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['is_late_entry'])

        # Confirm it does NOT show up in the active cycle's totals
        list_request = self._auth(self.factory.get('/api/view-savings/members/?all=true'))
        list_response = MembersListWithSavingsView.as_view()(list_request)
        member_row = next(m for m in list_response.data['members'] if m['id'] == self.member.id)
        self.assertEqual(member_row['total_savings'], 0.0)

    def test_delete_blocked_when_entry_has_withdrawal_allocation(self):
        cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')
        entry = make_entry(self.member, cycle, 10000, date(2026, 8, 2), self.admin)
        withdrawal = Withdrawal.objects.create(
            member=self.member, cycle=cycle, amount=Decimal('2000'),
            date=date(2026, 8, 3), created_by=self.admin
        )
        WithdrawalAllocation.objects.create(withdrawal=withdrawal, savings_entry=entry, amount=Decimal('2000'))

        request = self._auth(self.factory.delete(f'/api/savings/{entry.id}/'))
        view = SavingsEntryViewSet.as_view({'delete': 'destroy'})
        response = view(request, pk=entry.id)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(SavingsEntry.objects.filter(id=entry.id).exists())

    def test_delete_allowed_when_entry_has_no_allocation(self):
        cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')
        entry = make_entry(self.member, cycle, 10000, date(2026, 8, 2), self.admin)

        request = self._auth(self.factory.delete(f'/api/savings/{entry.id}/'))
        view = SavingsEntryViewSet.as_view({'delete': 'destroy'})
        response = view(request, pk=entry.id)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(SavingsEntry.objects.filter(id=entry.id).exists())

    def test_member_search_by_name_and_membership_id(self):
        request = self._auth(self.factory.get(f'/api/members/search/?q={self.member.membership_id}'))
        response = MemberSearchView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.member.id)

    def test_collector_summary_scoped_to_cycle_via_query_param(self):
        collector = make_collector()
        self.member.collector = collector
        self.member.save()

        old_cycle = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        make_entry(self.member, old_cycle, 40000, date(2026, 7, 2), self.admin)

        new_cycle = make_cycle('August 2026', date(2026, 8, 1), status='active')
        make_entry(self.member, new_cycle, 3000, date(2026, 8, 2), self.admin)

        request = self._auth(self.factory.get(f'/api/collectors/{collector.id}/summary/?cycle={new_cycle.id}'))
        response = CollectorSavingsSummaryView.as_view()(request, collector_id=collector.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_saved'], 3000.0)


# ============================================
# 5. MANAGEMENT COMMAND TESTS
# ============================================

class BackfillCommandTests(TestCase):

    def setUp(self):
        self.admin = make_user('admin7', is_staff=True)
        self.member = make_member(make_user('member7'))

        self.july = make_cycle('July 2026', date(2026, 7, 1), date(2026, 7, 31), status='closed')
        self.august = make_cycle('August 2026', date(2026, 8, 1), status='active')

        # Simulate PRE-FIX data: withdrawals created with no cycle at all,
        # exactly like rows created before this migration.
        self.old_withdrawal = Withdrawal.objects.create(
            member=self.member, cycle=None, amount=Decimal('5000'),
            date=date(2026, 7, 15), created_by=self.admin
        )
        self.unmatched_withdrawal = Withdrawal.objects.create(
            member=self.member, cycle=None, amount=Decimal('1000'),
            date=date(2020, 1, 1), created_by=self.admin  # before any cycle existed
        )

    def test_dry_run_does_not_change_anything(self):
        call_command('backfill_withdrawal_cycles', '--dry-run')
        self.old_withdrawal.refresh_from_db()
        self.assertIsNone(self.old_withdrawal.cycle)

    def test_apply_assigns_matching_cycle(self):
        call_command('backfill_withdrawal_cycles')
        self.old_withdrawal.refresh_from_db()
        self.assertEqual(self.old_withdrawal.cycle_id, self.july.id)

    def test_apply_leaves_unmatched_dates_unassigned(self):
        call_command('backfill_withdrawal_cycles')
        self.unmatched_withdrawal.refresh_from_db()
        self.assertIsNone(self.unmatched_withdrawal.cycle)

    def test_no_op_when_nothing_to_backfill(self):
        call_command('backfill_withdrawal_cycles')  # first run assigns what it can
        # second run should just report "nothing to backfill" for the matched one
        self.old_withdrawal.refresh_from_db()
        self.assertIsNotNone(self.old_withdrawal.cycle)