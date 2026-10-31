from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from ..config import Cfg


class DataStack(Stack):
    """Stateful pieces in their own stack: the bucket, the log group, the image and the pointer to it."""

    def __init__(self, scope: Construct, cid: str, cfg: Cfg, repo_root: str, **kw):
        super().__init__(scope, cid, termination_protection=True, **kw)
        self.bucket = s3.Bucket(
            self, "Bucket", block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True,
            encryption=s3.BucketEncryption.S3_MANAGED, versioned=True, removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[s3.LifecycleRule(noncurrent_version_expiration=Duration.days(3),
                                              abort_incomplete_multipart_upload_after=Duration.days(1))])
        self.log_group = logs.LogGroup(self, "AppLogs", log_group_name=f"{cfg.prefix}/app",
                                       retention=logs.RetentionDays.TWO_WEEKS, removal_policy=RemovalPolicy.DESTROY)
        self.image = ecr_assets.DockerImageAsset(
            self, "Image", directory=repo_root, platform=ecr_assets.Platform.custom(cfg.platform),
            build_args={"VITE_DISCORD_CLIENT_ID": cfg.discord_app_id})
        ssm.StringParameter(self, "ImageUri", parameter_name=f"{cfg.prefix}/image_uri", string_value=self.image.image_uri)
