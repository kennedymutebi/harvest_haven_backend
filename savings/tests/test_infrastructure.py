from datetime import date
from decimal import Decimal

from django.test import TestCase

from authentication.models import User, MemberProfile
from savings.models import SavingsCycle, SavingsEntry
from savings.infrastructure import (
    execute_withdrawal,
    get_all_member_profits_for_cycle,
    get_available_balance,
    get_member_balance,
    get_member_profit_for_cycle,
    InsufficientBalanceForWithdrawal,
)


class BroughtForwardIntegrationTest(TestCase):
    """Proves the actual Section-1 bug is fixed: money now genuinely
    carries forward from one cycle to the next."""

    def setUp(self):
        self.user = User.objects.create(username="kennedy", first_name="Kennedy", last_name="M")
        self.member = MemberProfile.objects.create(user=self.user, membership_id="MEM001")

        self.july = SavingsCycle.objects.create(
            name="July 2026", start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31), status="closed",
        )
        self.august = SavingsCycle.objects.create(
            name="August 2026", start_date=date(2026, 8, 1), status="active",
        )

        SavingsEntry.objects.create(
            member=self.member, cycle=self.july, amount=Decimal("120000"), date=date(2026, 7, 10),
        )
        SavingsEntry.objects.create(
            member=self.member, cycle=self.august, amount=Decimal("14000"), date=date(2026, 8, 5),
        )

    def test_matches_summary_docs_own_worked_example(self):
        # Section 3 of the summary doc: B/F 120,000 + This Month 14,000 = 134,000
        balance = get_member_balance(self.member.id, self.august)
        self.assertEqual(balance.brought_forward.amount, Decimal("120000.00"))
        self.assertEqual(balance.this_month.amount, Decimal("14000.00"))
        self.assertEqual(balance.total.amount, Decimal("134000.00"))

    def test_withdrawal_draws_from_lifetime_pool_not_just_active_cycle(self):
        # Old behavior would reject this: active cycle (August) only has
        # 14,000 in it. New behavior allows it because the lifetime pool
        # (134,000) covers it.
        execute_withdrawal(
            member_id=self.member.id, cycle=self.august, amount=Decimal("100000"),
            date=date(2026, 8, 15), reason="test", created_by=self.user,
        )
        balance = get_member_balance(self.member.id, self.august)
        # FIFO drew from July's old money first.
        self.assertEqual(balance.brought_forward.amount, Decimal("20000.00"))
        self.assertEqual(balance.this_month.amount, Decimal("14000.00"))
        self.assertEqual(balance.total.amount, Decimal("34000.00"))

    def test_insufficient_lifetime_balance_still_rejected(self):
        with self.assertRaises(InsufficientBalanceForWithdrawal):
            execute_withdrawal(
                member_id=self.member.id, cycle=self.august, amount=Decimal("999999"),
                date=date(2026, 8, 15), reason="test", created_by=self.user,
            )

    def test_get_available_balance_matches_total(self):
        self.assertEqual(get_available_balance(self.member.id), Decimal("134000.00"))


class ProfitIntegrationTest(TestCase):
    """Proves the per-member tiered charge is unaffected by same-month
    withdrawals, and that a per-member API is now possible."""

    def setUp(self):
        self.user = User.objects.create(username="admin")
        self.member_a = MemberProfile.objects.create(
            user=User.objects.create(username="alice"), membership_id="MEM-A"
        )
        self.member_b = MemberProfile.objects.create(
            user=User.objects.create(username="bob"), membership_id="MEM-B"
        )
        self.cycle = SavingsCycle.objects.create(
            name="September 2026", start_date=date(2026, 9, 1), status="active"
        )
        SavingsEntry.objects.create(
            member=self.member_a, cycle=self.cycle, amount=Decimal("250000"), date=date(2026, 9, 3),
        )
        SavingsEntry.objects.create(
            member=self.member_b, cycle=self.cycle, amount=Decimal("40000"), date=date(2026, 9, 4),
        )

    def test_per_member_charge_matches_doc_example(self):
        line = get_member_profit_for_cycle(self.member_a.id, self.cycle)
        self.assertEqual(line.charge.amount, Decimal("7000.00"))

    def test_withdrawal_does_not_change_the_charge(self):
        execute_withdrawal(
            member_id=self.member_a.id, cycle=self.cycle, amount=Decimal("200000"),
            date=date(2026, 9, 10), reason="test", created_by=self.user,
        )
        line = get_member_profit_for_cycle(self.member_a.id, self.cycle)
        self.assertEqual(line.charge.amount, Decimal("7000.00"))  # unchanged

    def test_profit_per_member_api_backbone(self):
        lines = get_all_member_profits_for_cycle(self.cycle)
        by_member = {line.member_id: line for line in lines}
        self.assertEqual(by_member[self.member_a.id].charge.amount, Decimal("7000.00"))
        self.assertEqual(by_member[self.member_b.id].charge.amount, Decimal("2000.00"))