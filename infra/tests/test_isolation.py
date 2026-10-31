"""Nothing is shared with, or changed in, anything that is not this application (spec 13.9)."""
import json
import re

ALLOWED_WILDCARD_RESOURCES = {
    "ecr:GetAuthorizationToken", "cloudwatch:PutMetricData", "kms:Decrypt", "ec2:DescribeNetworkInterfaces", "ec2:DescribeInstances"}


def statements(t):
    for res in t.find_resources("AWS::IAM::ManagedPolicy").values():
        s = res["Properties"]["PolicyDocument"]["Statement"]
        yield from (s if isinstance(s, list) else [s])


def listed(x):
    return x if isinstance(x, list) else [x]


def test_every_iam_statement_is_scoped_to_this_app(templates, cfg):
    seen = 0
    for st in statements(templates["host"]):
        for action in listed(st["Action"]):
            seen += 1
            for r in listed(st["Resource"]):
                if r == "*":
                    assert action in ALLOWED_WILDCARD_RESOURCES, f"{action} on *"
                else:
                    text = json.dumps(r)
                    assert any(k in text for k in (f"bamboozled/{cfg.env_name}/", "Bucket", "ecr", "LogGroup", "AppLogs",
                                                   "network-interface", "instance/*", "Eni")), text
    assert seen >= 12


def test_instance_attachment_is_limited_to_tagged_hosts(templates, cfg):
    stmts = [s for s in statements(templates["host"]) if "ec2:AttachNetworkInterface" in listed(s["Action"])]
    on_instances = [s for s in stmts if "instance/" in json.dumps(s["Resource"])]
    assert on_instances and all(s["Condition"]["StringEquals"] == {f"aws:ResourceTag/{cfg.host_tag_key}": cfg.host_tag_value}
                                for s in on_instances)


def test_the_only_security_group_has_one_inbound_rule_from_cloudfront(templates, cfg):
    t = templates["edge"]
    assert len(t.find_resources("AWS::EC2::SecurityGroup")) == 1
    rules = [r["Properties"] for r in t.find_resources("AWS::EC2::SecurityGroupIngress").values()]
    rules += [i for r in t.find_resources("AWS::EC2::SecurityGroup").values() for i in r["Properties"].get("SecurityGroupIngress", [])]
    assert len(rules) == 1
    assert (rules[0]["IpProtocol"], rules[0]["FromPort"], rules[0]["ToPort"]) == ("tcp", 8480, 8480)
    assert rules[0]["SourcePrefixListId"] == cfg.cloudfront_prefix_list_id and "CidrIp" not in rules[0]
    for name in ("data", "host", "monitoring"):
        assert not templates[name].find_resources("AWS::EC2::SecurityGroup")


def test_the_elastic_address_belongs_to_our_interface_only(templates):
    t = templates["edge"]
    assocs = t.find_resources("AWS::EC2::EIPAssociation")
    assert len(assocs) == 1
    props = next(iter(assocs.values()))["Properties"]
    assert "NetworkInterfaceId" in props and "InstanceId" not in props           # never the host's primary interface


def test_every_import_is_an_export_of_one_of_our_own_stacks(templates):
    exported = {out["Export"]["Name"] for t in templates.values() for out in t.to_json().get("Outputs", {}).values() if "Export" in out}
    imported = set(re.findall(r'"Fn::ImportValue": "([^"]+)"', json.dumps([t.to_json() for t in templates.values()])))
    assert imported <= exported
    assert all(n.startswith("Bamboozled") for n in exported)


def test_only_the_expected_resource_types_are_created_or_changed(templates):
    allowed = {
        "data": {"AWS::S3::Bucket", "AWS::S3::BucketPolicy", "AWS::Logs::LogGroup", "AWS::SSM::Parameter", "AWS::CDK::Metadata"},
        "edge": {"AWS::EC2::SecurityGroup", "AWS::EC2::SecurityGroupIngress", "AWS::EC2::NetworkInterface", "AWS::EC2::EIP", "AWS::EC2::EIPAssociation",
                 "AWS::SSM::Parameter", "AWS::CloudFront::Distribution", "AWS::CDK::Metadata"},
        "host": {"AWS::IAM::ManagedPolicy", "AWS::SSM::Parameter", "AWS::SSM::Document", "AWS::SSM::Association", "AWS::CDK::Metadata"},
        "monitoring": {"AWS::SNS::Topic", "AWS::SNS::Subscription", "AWS::CloudWatch::Alarm", "AWS::Budgets::Budget",
                       "AWS::CDK::Metadata"},
    }
    for name, t in templates.items():
        kinds = {r["Type"] for r in t.to_json()["Resources"].values()}
        assert kinds <= allowed[name], (name, kinds - allowed[name])


def test_resource_names_have_no_em_dash_and_are_prefixed(templates, cfg):
    for t in templates.values():
        body = json.dumps(t.to_json(), ensure_ascii=False)
        assert "—" not in body and "–" not in body
    names = re.findall(r'"(?:AlarmName|TopicName|BudgetName|ManagedPolicyName)": "([^"]+)"', json.dumps([t.to_json() for t in templates.values()]))
    assert names and all(n.startswith("bamboozled-") for n in names)
