from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SavingsEntryViewSet,
    SavingsCycleViewSet,
    WithdrawalViewSet,
    MembersListWithSavingsView,
    MemberSavingsDetailView,
    MemberSavingsHistoryView,
    CollectorSavingsSummaryView
)

router = DefaultRouter()
router.register(r'savings', SavingsEntryViewSet, basename='savings')
router.register(r'cycles', SavingsCycleViewSet, basename='cycles')
router.register(r'withdrawals', WithdrawalViewSet, basename='withdrawals')

urlpatterns = [
    # Existing ViewSet routes
    path('', include(router.urls)),
    
    # New View Savings routes
    path('view-savings/members/', MembersListWithSavingsView.as_view(), name='view-savings-members'),
    path('view-savings/members/<int:member_id>/', MemberSavingsDetailView.as_view(), name='view-savings-detail'),
    path('view-savings/members/<int:member_id>/history/', MemberSavingsHistoryView.as_view(), name='view-savings-history'),
    path('collectors/<int:collector_id>/summary/', CollectorSavingsSummaryView.as_view(), name='collector-savings-summary'),
]