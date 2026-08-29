"""
Management command: backfill_withdrawal_cycles

Run once, after `makemigrations` + `migrate` add the new `cycle` field to
Withdrawal. Existing withdrawals have cycle=NULL; this assigns each one to
the cycle its `date` actually falls inside, using the same date-range logic
your cycles already use.

Place this file at:
    savings/management/commands/backfill_withdrawal_cycles.py
(create the `management/` and `commands/` folders with empty __init__.py
files if they don't already exist in your `savings` app.)

Usage:
    python manage.py backfill_withdrawal_cycles          # apply
    python manage.py backfill_withdrawal_cycles --dry-run # preview only
"""

from django.core.management.base import BaseCommand
from savings.models import SavingsCycle, Withdrawal


class Command(BaseCommand):
    help = "Backfill cycle field on Withdrawal rows created before the cycle-scoping fix."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would change without saving anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        unassigned = Withdrawal.objects.filter(cycle__isnull=True).order_by('date')

        total = unassigned.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to backfill — every withdrawal already has a cycle."))
            return

        self.stdout.write(f"Found {total} withdrawal(s) with no cycle assigned.")

        cycles = list(SavingsCycle.objects.order_by('start_date'))
        assigned, unmatched = 0, 0

        for w in unassigned:
            matching_cycle = self._find_cycle_for_date(cycles, w.date)

            if matching_cycle is None:
                unmatched += 1
                self.stdout.write(self.style.WARNING(
                    f"  No matching cycle for withdrawal #{w.id} "
                    f"(member {w.member.membership_id}, date {w.date}) — left unassigned."
                ))
                continue

            self.stdout.write(
                f"  Withdrawal #{w.id} ({w.member.membership_id}, {w.date}) -> {matching_cycle.name}"
            )
            if not dry_run:
                w.cycle = matching_cycle
                w.save(update_fields=['cycle'])
            assigned += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n{'Would assign' if dry_run else 'Assigned'} {assigned} withdrawal(s). "
            f"{unmatched} left unmatched (no cycle covers that date — assign manually if needed)."
        ))

    @staticmethod
    def _find_cycle_for_date(cycles, date):
        """A cycle 'covers' a date if start_date <= date <= end_date
        (or end_date is null, meaning still open). If more than one
        matches, prefer the one with the latest start_date. If none
        match exactly, fall back to the most recent cycle that had
        already started by that date."""
        exact_matches = [
            c for c in cycles
            if c.start_date <= date and (c.end_date is None or c.end_date >= date)
        ]
        if exact_matches:
            return max(exact_matches, key=lambda c: c.start_date)

        started_before = [c for c in cycles if c.start_date <= date]
        if started_before:
            return max(started_before, key=lambda c: c.start_date)

        return None