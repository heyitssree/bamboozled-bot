from aws_cdk import Duration, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

from ..config import Cfg


class MonitoringStack(Stack):
    def __init__(self, scope: Construct, cid: str, cfg: Cfg, **kw):
        super().__init__(scope, cid, **kw)
        topic = sns.Topic(self, "Alerts", topic_name=f"bamboozled-{cfg.env_name}-alerts")
        topic.add_subscription(subs.EmailSubscription(cfg.alert_email))
        heartbeat = cw.Metric(namespace="Bamboozled", metric_name="Heartbeat", dimensions_map={"Env": cfg.env_name},
                              statistic="Sum", period=Duration.minutes(5))
        alarm = cw.Alarm(self, "NoHeartbeat", alarm_name=f"bamboozled-{cfg.env_name}-no-heartbeat", metric=heartbeat,
                         threshold=1, evaluation_periods=3, comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD,
                         treat_missing_data=cw.TreatMissingData.BREACHING,
                         alarm_description="No heartbeat for 15 minutes. Expected while run_enabled is false.")
        alarm.add_alarm_action(cw_actions.SnsAction(topic))
        budgets.CfnBudget(self, "Budget", budget=budgets.CfnBudget.BudgetDataProperty(
            budget_name=f"bamboozled-{cfg.env_name}-monthly", budget_type="COST", time_unit="MONTHLY",
            budget_limit=budgets.CfnBudget.SpendProperty(amount=cfg.budget_usd, unit="USD")),
            notifications_with_subscribers=[budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    comparison_operator="GREATER_THAN", notification_type="ACTUAL", threshold=80, threshold_type="PERCENTAGE"),
                subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=cfg.alert_email)])])
