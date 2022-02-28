# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import boto3
import os
import string
import uuid
from boto3.session import Session

ssm = boto3.client('ssm')
sts = boto3.client('sts')
ec2 = boto3.client('ec2')

def lambda_handler(event,context):
    env = event['env']
    TargetAccountsArray = sts.get_caller_identity()['Account']
    session = Session()
    TargetRegionIdsArray = session.get_available_regions('ec2')
    RunPatchBaselineOperation=event['patching_operation']
    RunPatchBaselineRebootOption=event['operation_post_patching']
    RunPatchBaselineInstallOverrideList=event['run_patch_baseline_install_override_list']
    TargetLocationMaxConcurrency='5'
    TargetLocationMaxErrors='13'
    ExecutionRoleName = os.environ["EXECUTION_ROLE_NAME"]
    AdministrationRoleName = os.environ["ADMINISTRATION_ROLE_NAME"]
    DocumentName = os.environ["DOCUMENT_NAME"]
    ResourceGroupKey = 'tag:maintenance_window'

    if len(RunPatchBaselineInstallOverrideList) > 0:
        parms = {
            'AutomationAssumeRole': [f'arn:aws:iam::{TargetAccountsArray}:role/{AdministrationRoleName}'],
            'Operation' : [f'{RunPatchBaselineOperation}'],
            'RebootOption' : [f'{RunPatchBaselineRebootOption}'],
            'InstallOverrideList' : [f'{RunPatchBaselineInstallOverrideList}'],
            'SnapshotId' : [str(uuid.uuid4())],
            'ResourceGroupKey' : [ResourceGroupKey],
            'ResourceGroupName' : [f'{env}_maintenance_window']
        }
    else:
        parms = {
            'AutomationAssumeRole': [f'arn:aws:iam::{TargetAccountsArray}:role/{AdministrationRoleName}'],
            'Operation' : [f'{RunPatchBaselineOperation}'],
            'RebootOption' : [f'{RunPatchBaselineRebootOption}'],
            'SnapshotId' : [str(uuid.uuid4())],
            'ResourceGroupKey' : [ResourceGroupKey],
            'ResourceGroupName' : [f'{env}_maintenance_window']
        }

    response = ssm.start_automation_execution(
        DocumentName=f'{DocumentName}',
        Parameters=parms,
        TargetLocations=[
            {
                'Accounts': [TargetAccountsArray],
                'Regions': TargetRegionIdsArray,
                'TargetLocationMaxConcurrency': f'{TargetLocationMaxConcurrency}',
                'TargetLocationMaxErrors': f'{TargetLocationMaxErrors}',
                'ExecutionRoleName': f'{ExecutionRoleName}'
            }
        ]
    )
    print(response)