import json

from aws_cdk.assertions import Match


def test_bucket_is_private_encrypted_and_ssl_only(templates):
    t = templates["data"]
    t.has_resource_properties("AWS::S3::Bucket", {"PublicAccessBlockConfiguration": {
        "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True}})
    t.has_resource_properties("AWS::S3::BucketPolicy", {"PolicyDocument": {"Statement": Match.array_with([
        Match.object_like({"Effect": "Deny", "Condition": {"Bool": {"aws:SecureTransport": "false"}}})])}})


def test_log_group_has_two_week_retention_and_the_image_pointer_exists(templates, cfg):
    t = templates["data"]
    t.has_resource_properties("AWS::Logs::LogGroup", {"LogGroupName": f"/bamboozled/{cfg.env_name}/app", "RetentionInDays": 14})
    t.has_resource_properties("AWS::SSM::Parameter", {"Name": f"/bamboozled/{cfg.env_name}/image_uri"})


def test_data_stack_is_termination_protected(stacks):
    assert stacks["data"].termination_protection is True


def test_host_stack_attaches_by_tag_and_starts_disabled(templates, cfg):
    t = templates["host"]
    t.has_resource_properties("AWS::SSM::Parameter", {"Name": f"/bamboozled/{cfg.env_name}/run_enabled", "Value": "false"})
    t.has_resource_properties("AWS::SSM::Association", {
        "Targets": [{"Key": f"tag:{cfg.host_tag_key}", "Values": [cfg.host_tag_value]}], "ScheduleExpression": "rate(30 minutes)"})
    t.has_resource_properties("AWS::IAM::ManagedPolicy", {"Roles": [cfg.host_role_name]})
    t.resource_count_is("AWS::IAM::Role", 0)                                      # no role is created or changed


def test_install_document_carries_the_script(templates):
    doc = next(r for r in templates["host"].find_resources("AWS::SSM::Document").values())
    lines = doc["Properties"]["Content"]["mainSteps"][0]["inputs"]["runCommand"]
    text = "\n".join(lines)
    assert "docker run" in text and "[Unit]" in text and "@@" not in text
    assert text.rstrip().endswith("'{{eniParam}}'")


def test_edge_forwards_the_websocket_on_api_and_caches_nothing_there(templates):
    t = templates["edge"]
    dist = next(iter(t.find_resources("AWS::CloudFront::Distribution").values()))["Properties"]["DistributionConfig"]
    api = next(b for b in dist["CacheBehaviors"] if b["PathPattern"] == "/api/*")
    assert api["AllowedMethods"] == ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"]
    # managed policies: CachingDisabled and AllViewerExceptHostHeader (forwards Upgrade / Sec-WebSocket-* headers)
    assert api["CachePolicyId"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    assert api["OriginRequestPolicyId"] == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    assert dist["PriceClass"] == "PriceClass_100" and dist["DefaultCacheBehavior"]["ViewerProtocolPolicy"] == "redirect-to-https"
    for origin in dist["Origins"]:
        assert origin["OriginCustomHeaders"][0]["HeaderName"] == "X-Origin-Verify"
        assert origin["CustomOriginConfig"]["OriginProtocolPolicy"] == "http-only"


def test_monitoring_has_a_heartbeat_alarm_an_email_and_a_budget(templates, cfg):
    t = templates["monitoring"]
    t.has_resource_properties("AWS::CloudWatch::Alarm", {
        "Namespace": "Bamboozled", "MetricName": "Heartbeat", "Dimensions": [{"Name": "Env", "Value": cfg.env_name}],
        "EvaluationPeriods": 3, "Period": 300, "TreatMissingData": "breaching"})
    t.has_resource_properties("AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": cfg.alert_email})
    t.has_resource_properties("AWS::Budgets::Budget", {"Budget": Match.object_like({"TimeUnit": "MONTHLY"})})


def test_the_synthesised_templates_are_json_serialisable(templates):
    for t in templates.values():
        json.dumps(t.to_json())
