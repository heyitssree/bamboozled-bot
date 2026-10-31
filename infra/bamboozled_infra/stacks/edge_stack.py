from aws_cdk import CfnOutput, Duration, Fn, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from ..config import Cfg

PORT = 8480


class EdgeStack(Stack):
    """A second network interface of our own (own security group, own address) with CloudFront in front of it, so the
    host's own interface, address and security group are never touched."""

    def __init__(self, scope: Construct, cid: str, cfg: Cfg, **kw):
        super().__init__(scope, cid, **kw)
        vpc = ec2.Vpc.from_vpc_attributes(self, "Vpc", vpc_id=cfg.host_vpc_id, availability_zones=[cfg.host_az])
        sg = ec2.SecurityGroup(self, "IngressSg", vpc=vpc, allow_all_outbound=True,
                               description="Bamboozled ingress - CloudFront only")
        sg.add_ingress_rule(ec2.Peer.prefix_list(cfg.cloudfront_prefix_list_id), ec2.Port.tcp(PORT), "CloudFront origin-facing")
        self.eni = ec2.CfnNetworkInterface(self, "Eni", subnet_id=cfg.host_subnet_id, group_set=[sg.security_group_id],
                                           description="Bamboozled ingress")
        eip = ec2.CfnEIP(self, "Eip", domain="vpc")
        ec2.CfnEIPAssociation(self, "EipAssoc", allocation_id=eip.attr_allocation_id, network_interface_id=self.eni.ref)
        self.eni_param = ssm.StringParameter(self, "EniParam", parameter_name=f"{cfg.prefix}/eni_id", string_value=self.eni.ref)
        suffix = "compute-1.amazonaws.com" if self.region == "us-east-1" else f"{self.region}.compute.amazonaws.com"
        origin_host = Fn.join("", ["ec2-", Fn.join("-", Fn.split(".", eip.ref)), f".{suffix}"])

        def origin():
            return origins.HttpOrigin(origin_host, protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY, http_port=PORT,
                                      read_timeout=Duration.seconds(60), custom_headers={"X-Origin-Verify": cfg.origin_verify_value})
        self.dist = cloudfront.Distribution(
            self, "Dist",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origin(), viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED, allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD),
            additional_behaviors={"/api/*": cloudfront.BehaviorOptions(          # REST and the WebSocket
                origin=origin(), viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL)},
            price_class=cloudfront.PriceClass.PRICE_CLASS_100, http_version=cloudfront.HttpVersion.HTTP2)
        CfnOutput(self, "UrlMappingTarget", value=self.dist.distribution_domain_name,
                  description="Discord Developer Portal, URL Mappings, prefix /")
