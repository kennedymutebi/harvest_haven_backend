"""
authentication/tests/test_collector_endpoints.py

Tests for the collector page backend (phase 1): list, edit, guarded delete,
loading a collector's members, and reassigning members.

Run:  python manage.py test authentication.tests.test_collector_endpoints
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from authentication.models import User, MemberProfile, Collector
from savings.models import SavingsCycle, SavingsEntry

BASE = '/api/auth/collectors/'


class CollectorTestCase(TestCase):
    """Team A has 3 members (2 active, 1 inactive). Team B and Team Empty
    have none. The logged-in user is staff."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(username='admin', email='admin@test.com', password='pass12345')
        self.admin.is_staff = True
        self.admin.save()
        self.client.force_authenticate(user=self.admin)

        self.team_a = Collector.objects.create(name='Team A')
        self.team_b = Collector.objects.create(name='Team B')
        self.team_empty = Collector.objects.create(name='Team Empty')

        self.alice = self.make_member(1, self.team_a, first='Alice')
        self.brian = self.make_member(2, self.team_a, first='Brian')
        self.cathy = self.make_member(3, self.team_a, first='Cathy', active=False)

    def make_member(self, n, collector, first='Member', active=True):
        user = User.objects.create_user(
            username=f'm{n}', email=f'm{n}@test.com', password='pass12345',
            first_name=first, last_name='T',
        )
        return MemberProfile.objects.create(
            user=user, membership_id=f'MEM{n:03d}', registered_by=self.admin,
            collector=collector, is_active_member=active,
        )

    def member_ids(self, collector):
        return set(MemberProfile.objects.filter(collector=collector).values_list('pk', flat=True))

    def reassign(self, source, payload):
        return self.client.post(f'{BASE}{source.id}/reassign-members/', payload, format='json')


class AccessTest(CollectorTestCase):
    def test_anonymous_rejected(self):
        resp = APIClient().get(BASE)
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_non_staff_cannot_delete_or_reassign(self):
        normal = User.objects.create_user(username='normal', email='n@test.com', password='pass12345')
        self.client.force_authenticate(user=normal)
        self.assertEqual(self.client.delete(f'{BASE}{self.team_empty.id}/').status_code, status.HTTP_403_FORBIDDEN)
        resp = self.reassign(self.team_a, {'target_collector': self.team_b.id, 'all': True})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.member_ids(self.team_a), {self.alice.id, self.brian.id, self.cathy.id})


class CollectorCrudTest(CollectorTestCase):
    def test_list_shows_members_count(self):
        resp = self.client.get(BASE)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        counts = {r['name']: r['members_count'] for r in rows}
        self.assertEqual(counts, {'Team A': 3, 'Team B': 0, 'Team Empty': 0})

    def test_create_collector(self):
        resp = self.client.post(BASE, {'name': '  Team C  ', 'phone_number': '+256700123456'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'Team C')  # trimmed
        self.assertEqual(resp.data['members_count'], 0)

    def test_create_rejects_blank_name(self):
        resp = self.client.post(BASE, {'name': '   '}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_edit_collector(self):
        resp = self.client.patch(f'{BASE}{self.team_a.id}/', {'name': 'Team Alpha'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.team_a.refresh_from_db()
        self.assertEqual(self.team_a.name, 'Team Alpha')
        self.assertEqual(resp.data['members_count'], 3)


class CollectorDeleteTest(CollectorTestCase):
    def test_delete_refused_while_members_attached(self):
        resp = self.client.delete(f'{BASE}{self.team_a.id}/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['members_count'], 3)
        self.assertTrue(Collector.objects.filter(pk=self.team_a.id).exists())
        self.assertEqual(len(self.member_ids(self.team_a)), 3)  # nobody detached

    def test_delete_refused_even_if_only_inactive_member_left(self):
        MemberProfile.objects.filter(pk__in=[self.alice.id, self.brian.id]).update(collector=self.team_b)
        resp = self.client.delete(f'{BASE}{self.team_a.id}/')  # only inactive Cathy remains
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Collector.objects.filter(pk=self.team_a.id).exists())

    def test_delete_succeeds_when_no_members(self):
        resp = self.client.delete(f'{BASE}{self.team_empty.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Collector.objects.filter(pk=self.team_empty.id).exists())

    def test_delete_unknown_collector_404(self):
        self.assertEqual(self.client.delete(f'{BASE}99999/').status_code, status.HTTP_404_NOT_FOUND)


class CollectorMembersTest(CollectorTestCase):
    def test_returns_all_members_including_inactive(self):
        resp = self.client.get(f'{BASE}{self.team_a.id}/members/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 3)
        self.assertEqual({r['id'] for r in resp.data['results']}, {self.alice.id, self.brian.id, self.cathy.id})

    def test_only_this_collectors_members(self):
        other = self.make_member(9, self.team_b, first='Zed')
        resp = self.client.get(f'{BASE}{self.team_a.id}/members/')
        self.assertNotIn(other.id, {r['id'] for r in resp.data['results']})

    def test_search_filters_members(self):
        resp = self.client.get(f'{BASE}{self.team_a.id}/members/?search=Alice')
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['id'], self.alice.id)

    def test_empty_collector_returns_empty_list(self):
        resp = self.client.get(f'{BASE}{self.team_empty.id}/members/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 0)


class ReassignMembersTest(CollectorTestCase):
    def test_move_all(self):
        resp = self.reassign(self.team_a, {'target_collector': self.team_b.id, 'all': True})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['moved'], 3)
        self.assertEqual(resp.data['remaining_members'], 0)
        self.assertTrue(resp.data['can_delete_source'])
        self.assertEqual(self.member_ids(self.team_a), set())
        self.assertEqual(self.member_ids(self.team_b), {self.alice.id, self.brian.id, self.cathy.id})

    def test_move_selected_only(self):
        resp = self.reassign(self.team_a, {'target_collector': self.team_b.id, 'member_ids': [self.alice.id]})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['moved'], 1)
        self.assertEqual(resp.data['remaining_members'], 2)
        self.assertFalse(resp.data['can_delete_source'])
        self.assertEqual(self.member_ids(self.team_b), {self.alice.id})
        self.assertEqual(self.member_ids(self.team_a), {self.brian.id, self.cathy.id})

    def test_move_one_by_one_to_different_collectors(self):
        resp = self.reassign(self.team_a, {'moves': [
            {'member_id': self.alice.id, 'collector_id': self.team_b.id},
            {'member_id': self.brian.id, 'collector_id': self.team_empty.id},
        ]})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(self.member_ids(self.team_b), {self.alice.id})
        self.assertEqual(self.member_ids(self.team_empty), {self.brian.id})
        self.assertEqual(self.member_ids(self.team_a), {self.cathy.id})

    def test_full_flow_move_all_then_delete(self):
        self.assertEqual(self.client.delete(f'{BASE}{self.team_a.id}/').status_code, status.HTTP_400_BAD_REQUEST)
        self.reassign(self.team_a, {'target_collector': self.team_b.id, 'all': True})
        self.assertEqual(self.client.delete(f'{BASE}{self.team_a.id}/').status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(len(self.member_ids(self.team_b)), 3)  # members survived the delete

    def test_atomic_when_a_member_is_not_in_source(self):
        stranger = self.make_member(9, self.team_b, first='Zed')
        resp = self.reassign(self.team_a, {
            'target_collector': self.team_empty.id,
            'member_ids': [self.alice.id, stranger.id],  # stranger is NOT in Team A
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.member_ids(self.team_empty), set())  # Alice was NOT moved either
        self.assertEqual(self.member_ids(self.team_a), {self.alice.id, self.brian.id, self.cathy.id})

    def test_atomic_when_one_move_has_bad_target(self):
        resp = self.reassign(self.team_a, {'moves': [
            {'member_id': self.alice.id, 'collector_id': self.team_b.id},
            {'member_id': self.brian.id, 'collector_id': 99999},
        ]})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.member_ids(self.team_b), set())  # Alice not moved

    def test_inactive_target_rejected(self):
        self.team_b.is_active = False
        self.team_b.save()
        resp = self.reassign(self.team_a, {'target_collector': self.team_b.id, 'all': True})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(self.member_ids(self.team_a)), 3)

    def test_moving_to_same_collector_is_nothing_to_move(self):
        resp = self.reassign(self.team_a, {'target_collector': self.team_a.id, 'all': True})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_target_rejected(self):
        resp = self.reassign(self.team_a, {'all': True})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_member_selection_rejected(self):
        resp = self.reassign(self.team_a, {'target_collector': self.team_b.id})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_garbage_ids_rejected(self):
        resp = self.reassign(self.team_a, {'target_collector': self.team_b.id, 'member_ids': ['abc']})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_savings_are_untouched_by_a_move(self):
        cycle = SavingsCycle.objects.create(name='August 2026', start_date=date(2026, 8, 1), status='active')
        entry = SavingsEntry.objects.create(
            member=self.alice, cycle=cycle, amount=Decimal('14000'), date=date(2026, 8, 5),
        )
        self.reassign(self.team_a, {'target_collector': self.team_b.id, 'all': True})
        entry.refresh_from_db()
        self.assertEqual(entry.member_id, self.alice.id)
        self.assertEqual(entry.amount, Decimal('14000'))
        self.assertEqual(SavingsEntry.objects.count(), 1)