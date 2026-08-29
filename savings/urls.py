from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SavingsEntryViewSet,
    SavingsCycleViewSet,
    WithdrawalViewSet,
    MembersListWithSavingsView,
    MemberSavingsDetailView,
    MemberSavingsHistoryView,
    CollectorSavingsSummaryView,
    LateSavingsEntryView,
    MemberSearchView,
    CycleExportView,
    MemberHistoryExportView,
    CollectorExportView,
    AllCollectorsExportView,
    CyclePdfExportView,
    MemberStatementPdfExportView,
    CollectorPdfExportView,
)

router = DefaultRouter()
router.register(r'savings', SavingsEntryViewSet, basename='savings')
router.register(r'cycles', SavingsCycleViewSet, basename='cycles')
router.register(r'withdrawals', WithdrawalViewSet, basename='withdrawals')

urlpatterns = [
    # Existing ViewSet routes
    path('', include(router.urls)),

    # View Savings routes
    path('view-savings/members/', MembersListWithSavingsView.as_view(), name='view-savings-members'),
    path('view-savings/members/<int:member_id>/', MemberSavingsDetailView.as_view(), name='view-savings-detail'),
    path('view-savings/members/<int:member_id>/history/', MemberSavingsHistoryView.as_view(), name='view-savings-history'),
    path('collectors/<int:collector_id>/summary/', CollectorSavingsSummaryView.as_view(), name='collector-savings-summary'),

    # Late-save workflow
    path('savings/late-entry/', LateSavingsEntryView.as_view(), name='savings-late-entry'),
    path('members/search/', MemberSearchView.as_view(), name='members-search'),

    # Excel exports
    path('export/cycle/', CycleExportView.as_view(), name='export-cycle'),
    path('export/member/<int:member_id>/', MemberHistoryExportView.as_view(), name='export-member-history'),
    path('export/collector/<int:collector_id>/', CollectorExportView.as_view(), name='export-collector'),
    path('export/collectors/', AllCollectorsExportView.as_view(), name='export-all-collectors'),

    # PDF exports
    path('export/cycle/pdf/', CyclePdfExportView.as_view(), name='export-cycle-pdf'),
    path('export/member/<int:member_id>/pdf/', MemberStatementPdfExportView.as_view(), name='export-member-pdf'),
    path('export/collector/<int:collector_id>/pdf/', CollectorPdfExportView.as_view(), name='export-collector-pdf'),
]