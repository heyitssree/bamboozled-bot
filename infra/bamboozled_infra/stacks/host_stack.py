from aws_cdk import ArnFormat, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from ..config import Cfg
from ..install import PARAMS, install_commands

class HostStack(Stack):
    """Attaches to the existing VM by tag: a managed policy on its role, and an association that installs us."""

    def __init__(self, scope: Construct, cid: str, cfg: Cfg, data, edge, **kw):
        super().__init__(scope, cid, **kw)
        host_role = iam.Role.from_role_name(self, "HostRole", cfg.host_role_name)
        iam.ManagedPolicy(self, "BamboozledAccess", managed_policy_name=f"bamboozled-{cfg.env_name}-host-access",
                          roles=[host_role], statements=[
            iam.PolicyStatement(actions=["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
                                resources=[self.format_arn(service="ssm", resource="parameter", resource_name=f"bamboozled/{cfg.env_name}/*",
                                                           arn_format=ArnFormat.SLASH_RESOURCE_NAME)]),
            iam.PolicyStatement(actions=["kms:Decrypt"], resources=["*"],
                                conditions={"StringEquals": {"kms:ViaService": f"ssm.{self.region}.amazonaws.com"}}),
            iam.PolicyStatement(actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:GetBucketLocation"],
                                resources=[data.bucket.bucket_arn, data.bucket.arn_for_objects("*")]),
            iam.PolicyStatement(actions=["ecr:GetAuthorizationToken"], resources=["*"]),
            iam.PolicyStatement(actions=["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"],
                                resources=[data.image.repository.repository_arn]),
            iam.PolicyStatement(actions=["logs:CreateLogStream", "logs:PutLogEvents"], resources=[data.log_group.log_group_arn + ":*"]),
            iam.PolicyStatement(actions=["cloudwatch:PutMetricData"], resources=["*"],
                                conditions={"StringEquals": {"cloudwatch:namespace": "Bamboozled"}}),
            iam.PolicyStatement(actions=["ec2:AttachNetworkInterface"],             # authorised per resource: our ENI ...
                                resources=[f"arn:aws:ec2:{self.region}:{self.account}:network-interface/{edge.eni.ref}"]),
            iam.PolicyStatement(actions=["ec2:AttachNetworkInterface"],             # ... and only onto tagged hosts
                                resources=[f"arn:aws:ec2:{self.region}:{self.account}:instance/*"],
                                conditions={"StringEquals": {f"aws:ResourceTag/{cfg.host_tag_key}": cfg.host_tag_value}}),
            iam.PolicyStatement(actions=["ec2:DescribeNetworkInterfaces", "ec2:DescribeInstances"], resources=["*"]),
        ])
        ssm.StringParameter(self, "RunEnabled", parameter_name=f"{cfg.prefix}/run_enabled", string_value="false")
        doc = ssm.CfnDocument(
            self, "InstallDoc", document_type="Command", document_format="JSON", name=f"bamboozled-{cfg.env_name}-install",
            content={"schemaVersion": "2.2", "description": "Install or update Bamboozled on this host (idempotent)",
                     "parameters": {k: {"type": "String"} for k in PARAMS},
                     "mainSteps": [{"action": "aws:runShellScript", "name": "install",
                                    "inputs": {"runCommand": install_commands()}}]})
        ssm.CfnAssociation(
            self, "InstallAssoc", name=doc.ref, association_name=f"bamboozled-{cfg.env_name}",
            targets=[ssm.CfnAssociation.TargetProperty(key=f"tag:{cfg.host_tag_key}", values=[cfg.host_tag_value])],
            schedule_expression="rate(30 minutes)", max_concurrency="1", max_errors="1", apply_only_at_cron_interval=False,
            parameters={"prefix": [cfg.prefix], "env": [cfg.env_name], "region": [self.region], "port": ["8480"],
                        "logGroup": [data.log_group.log_group_name], "bucket": [data.bucket.bucket_name],
                        "eniParam": [edge.eni_param.parameter_name]})
