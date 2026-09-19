from django.urls import path, include
from rest_framework.routers import SimpleRouter
from .views import (
    SavingsEntryViewSet,
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
from .profit_views import MemberProfitView, CycleProfitView

router = SimpleRouter()

# ORDER MATTERS: withdrawals MUST be registered before the empty-prefix
# savings registration. SimpleRouter emits patterns in registration
# order, and Django matches top-to-bottom - the empty-prefix router's
# detail pattern `^(?P<pk>[^/.]+)/$` is a wildcard that would otherwise
# swallow "withdrawals/" as if it were a numeric pk, returning 405/404
# from SavingsEntryViewSet instead of ever reaching WithdrawalViewSet.
router.register(r'withdrawals', WithdrawalViewSet, basename='withdrawals')
router.register(r'', SavingsEntryViewSet, basename='savings')

urlpatterns = [
    path('late-entry/', LateSavingsEntryView.as_view(), name='savings-late-entry'),
    path('profit/', CycleProfitView.as_view(), name='cycle-profit'),

    path('', include(router.urls)),

    path('view-savings/members/', MembersListWithSavingsView.as_view(), name='view-savings-members'),
    path('view-savings/members/<int:member_id>/', MemberSavingsDetailView.as_view(), name='view-savings-detail'),
    path('view-savings/members/<int:member_id>/history/', MemberSavingsHistoryView.as_view(), name='view-savings-history'),
    path('collectors/<int:collector_id>/summary/', CollectorSavingsSummaryView.as_view(), name='collector-savings-summary'),

    path('members/search/', MemberSearchView.as_view(), name='members-search'),

    # FIXED: was 'savings/members/<int:member_id>/profit/' — this file is
    # already mounted at api/savings/, so the leading 'savings/' doubled
    # the prefix to api/savings/savings/members/.../profit/, which nothing
    # could ever reach.
    path('members/<int:member_id>/profit/', MemberProfitView.as_view(), name='member-profit'),

    path('export/cycle/', CycleExportView.as_view(), name='export-cycle'),
    path('export/member/<int:member_id>/', MemberHistoryExportView.as_view(), name='export-member-history'),
    path('export/collector/<int:collector_id>/', CollectorExportView.as_view(), name='export-collector'),
    path('export/collectors/', AllCollectorsExportView.as_view(), name='export-all-collectors'),

    path('export/cycle/pdf/', CyclePdfExportView.as_view(), name='export-cycle-pdf'),
    path('export/member/<int:member_id>/pdf/', MemberStatementPdfExportView.as_view(), name='export-member-pdf'),
    path('export/collector/<int:collector_id>/pdf/', CollectorPdfExportView.as_view(), name='export-collector-pdf'),
]