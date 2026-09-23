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
from .report_views import (                                    # ADDED
    cycle_report_json,                                          # ADDED
    member_statement_json,                                      # ADDED
    collector_summary_json,                                     # ADDED
    all_collectors_summary_json,                                # ADDED
)                                                                # ADDED

router = SimpleRouter()
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
    path('members/<int:member_id>/profit/', MemberProfitView.as_view(), name='member-profit'),

    path('export/cycle/', CycleExportView.as_view(), name='export-cycle'),
    path('export/member/<int:member_id>/', MemberHistoryExportView.as_view(), name='export-member-history'),
    path('export/collector/<int:collector_id>/', CollectorExportView.as_view(), name='export-collector'),
    path('export/collectors/', AllCollectorsExportView.as_view(), name='export-all-collectors'),
    path('export/cycle/pdf/', CyclePdfExportView.as_view(), name='export-cycle-pdf'),
    path('export/member/<int:member_id>/pdf/', MemberStatementPdfExportView.as_view(), name='export-member-pdf'),
    path('export/collector/<int:collector_id>/pdf/', CollectorPdfExportView.as_view(), name='export-collector-pdf'),

    path('report-data/cycle/', cycle_report_json, name='report-data-cycle'),                              # ADDED
    path('report-data/member/<int:member_id>/', member_statement_json, name='report-data-member'),        # ADDED
    path('report-data/collector/<int:collector_id>/', collector_summary_json, name='report-data-collector'),  # ADDED
    path('report-data/collectors/', all_collectors_summary_json, name='report-data-collectors'),           # ADDED
]