from django.urls import path
from .views import (
    DashboardView, 
    SavingsTrendView, 
    WeeklyDepositView,
    RecentTransactionsView,
    TopSaversView
)

urlpatterns = [
    path('stats/', DashboardView.as_view(), name='dashboard-stats'),
    path('trends/', SavingsTrendView.as_view(), name='savings-trends'),
    path('weekly-deposits/', WeeklyDepositView.as_view(), name='weekly-deposits'),
    path('transactions/recent/', RecentTransactionsView.as_view(), name='recent-transactions'),
    path('top-savers/', TopSaversView.as_view(), name='top-savers'),
]