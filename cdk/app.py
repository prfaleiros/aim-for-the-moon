#!/usr/bin/env python3
import os
import shutil

import aws_cdk as cdk

from stacks.moonswitch_stack import MoonswitchStack, ROOT

# Bundle the machine config with the Lambda (gitignored copy; source of truth is config/config.json)
shutil.copy(os.path.join(ROOT, "config", "config.json"), os.path.join(ROOT, "lambdas", "api", "config.json"))

app = cdk.App()
MoonswitchStack(app, "MoonswitchStack", env=cdk.Environment(
    account=app.node.try_get_context("account") or os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region="us-east-1",
))
app.synth()
