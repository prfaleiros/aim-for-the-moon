import os

from aws_cdk import (
    Stack, Duration, RemovalPolicy, CfnOutput,
    aws_dynamodb as ddb,
    aws_s3 as s3,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
)
from constructs import Construct

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class MoonswitchStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        table = ddb.Table(
            self, "Table",
            table_name="Moonswitch",
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True),
            removal_policy=RemovalPolicy.RETAIN,
        )
        table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=ddb.Attribute(name="GSI1PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="GSI1SK", type=ddb.AttributeType.STRING),
            projection_type=ddb.ProjectionType.ALL,
        )

        # Photos are phase 2; the bucket is created now so the stack doesn't change shape later.
        photos = s3.Bucket(
            self, "PhotosBucket",
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # lambdas/api; app.py copies config/config.json next to the handler before synth
        # (bundled instead of a config bucket: redeploy to change it, same as the cached-config rule).
        fn = _lambda.Function(
            self, "Api",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="handler.handler",
            code=_lambda.Code.from_asset(os.path.join(ROOT, "lambdas", "api"), exclude=["__pycache__", "**/__pycache__"]),
            environment={"TABLE_NAME": table.table_name, "PHOTOS_BUCKET": photos.bucket_name},
            timeout=Duration.seconds(15),
            memory_size=256,
        )
        table.grant_read_write_data(fn)
        photos.grant_read_write(fn)

        api = apigw.LambdaRestApi(
            self, "Api_",
            rest_api_name="Moonswitch",
            handler=fn,
            proxy=True,
            cloud_watch_role=False,  # account-wide singleton; leave it to whichever stack already owns it
            default_method_options=apigw.MethodOptions(api_key_required=True),
        )
        key = api.add_api_key("ApiKey")
        plan = api.add_usage_plan("UsagePlan", throttle=apigw.ThrottleSettings(rate_limit=10, burst_limit=20))
        plan.add_api_key(key)
        plan.add_api_stage(stage=api.deployment_stage)

        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "ApiKeyId", value=key.key_id)
