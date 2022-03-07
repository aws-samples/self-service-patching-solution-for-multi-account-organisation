# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import boto3
import logging
import os
import string
import uuid
from boto3.session import Session

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)
CH = logging.StreamHandler()
CH.setLevel(logging.INFO)
FORMATTER = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
CH.setFormatter(FORMATTER)
LOGGER.addHandler(CH)


class PatchingASG(object):
    """
    # Class: PatchingASG
    # Description: Patch ASG's
    """

    def __init__(self, event, context):
        self.event = event
        self.context = context
        self.exception = []

        ssm_client = boto3.client('ssm')        
        sts_client = boto3.client('sts')

        self.execution_role_name = os.environ["EXECUTION_ROLE_NAME"]
        self.administration_role_name = os.environ["ADMINISTRATION_ROLE_NAME"]
        self.document_name = os.environ["DOCUMENT_NAME"]
        self.lambda_name = os.environ["ASG_UPDATE_LAMBDA_NAME"] 
        self.asg_execution_role_name = os.environ["ASG_EXECUTION_ROLE_NAME"]
        self.asg_document_name = os.environ["ASG_DOCUMENT_NAME"]
        self.profile_role_name = os.environ["PROFILE_ROLE_NAME"]
        self.patching_template_region = os.environ["PATCHING_TEMPLATE_REGION"] 
        regions = os.environ["WORKLOAD_REGIONS"]
        self.regions = regions.split(",")
        self.accounts_id = sts_client.get_caller_identity()['Account']
        # session = Session()
        # self.regions = session.get_available_regions('ec2')
        self.target_location_max_concurrency='1'
        self.target_location_max_errors='1'        
        try:
            self.env = self.event['env']
            self.retain_healthy_percentage = self.event['retain_healthy_percentage']
            self.refresh_asg_instances = self.event['refresh_asg_instances']
            self.patching_operation = self.event['patching_operation']
            self.run_patch_baseline_install_override_list = self.event['run_patch_baseline_install_override_list']            
            print("event", self.event)
        except Exception as exception:
            self.reason_data = "Missing required property %s" % exception
            LOGGER.error(self.reason_data)
            print("Failed in except block of __init__")
            

    def describe_asg(self,env): 
        try:
            response = self.as_client.describe_auto_scaling_groups(MaxRecords=100)
            asg_name=[]
            subnet_id = []
            launch_config_name=[]
            image_id = []
            sg_id = []

            for group in response['AutoScalingGroups']:
                for tags in group['Tags']:
                    if tags['Key'] == 'maintenance_window' and tags['Value'] == env+'_maintenance_window':
                        asg_name.append(group['AutoScalingGroupName'])
                        subnet_tmp = group['VPCZoneIdentifier']
                        try:
                            subnet_tmp = subnet_tmp.split(',')[0]
                        except Exception as exp:
                            print(str(exp))
                        subnet_id.append(subnet_tmp)
                        try:
                            launch_config_name.append(group['LaunchConfigurationName'])
                            image_id.append(self.as_client.describe_launch_configurations(LaunchConfigurationNames=[group['LaunchConfigurationName']])['LaunchConfigurations'][0]['ImageId'])
                        except Exception as exp:
                            print('Launch configuration not found')
                            launch_template = group['LaunchTemplate']['LaunchTemplateId']
                            launch_template_version = group['LaunchTemplate']['Version']
                            response = self.ec2_client.describe_launch_template_versions(LaunchTemplateId=launch_template,Versions=[launch_template_version])
                            image_id.append(response['LaunchTemplateVersions'][0]['LaunchTemplateData']['ImageId'])
                        response = self.ec2_client.describe_subnets(SubnetIds=[subnet_tmp])
                        vpc_id = response['Subnets'][0]['VpcId']
                        try: 
                            response = self.ec2_client.describe_security_groups(
                                Filters=[
                                    {
                                        'Name': 'group-name',
                                        'Values': ['ASGPatchingSG']
                                    },
                                    {
                                        'Name': 'vpc-id',
                                        'Values': [vpc_id]
                                    }                            
                                ]                       
                            )
                            sg_id_tmp = response['SecurityGroups'][0]['GroupId']                    
                            rule_exists = False
                            for rule in response['SecurityGroups'][0]['IpPermissionsEgress']:
                                if rule['IpProtocol'] == '-1' and rule['IpRanges'][0]['CidrIp'] == '0.0.0.0/0':
                                    print('Patching SG found')
                                    rule_exists = True
                            if rule_exists != True: 
                                print('Patching SG found - adding rule')
                                response = self.ec2_client.authorize_security_group_egress(
                                GroupId=sg_id_tmp,
                                IpPermissions=[{
                                        'FromPort': -1,
                                        'IpProtocol': '-1',
                                        'IpRanges': [{
                                                'CidrIp': '0.0.0.0/0',
                                                'Description': 'string'
                                            }],
                                        'ToPort': -1
                                    }])
                            sg_id.append(sg_id_tmp)
                        except Exception as exp:
                            print('No Patching SG ' +str(exp))
                            response = self.ec2_client.create_security_group(
                                Description='Security Group for Patching ASGs',
                                GroupName='ASGPatchingSG',
                                VpcId=vpc_id
                            )
                            sg_id.append(response['GroupId'])

            return asg_name, subnet_id, image_id, sg_id

        except Exception as exp:  
            print('No such ASG'+str(exp))


    def invoke_ssm_doc(self,asg_name,subnet_id,image_id,sg_id): 
        for i in range(len(asg_name)):
            if self.patching_operation == "Scan":
                parmsASG = {
                    'AutomationAssumeRole': [f'arn:aws:iam::{self.accounts_id}:role/{self.administration_role_name}'],
                    'Operation' : [self.patching_operation],
                    'SnapshotId' : [str(uuid.uuid4())],
                    'ResourceGroupKey' : ['tag:aws:autoscaling:groupName'],
                    'ResourceGroupName' : [asg_name[i]]
                }
                if len(self.run_patch_baseline_install_override_list) > 0:
                    parmsASG['InstallOverrideList'] = [self.run_patch_baseline_install_override_list]

                response = self.ssm_client.start_automation_execution(
                    DocumentName=f'{self.document_name}',
                    Parameters=parmsASG,
                    TargetLocations=[
                        {
                            'Accounts': [self.accounts_id],
                            'Regions': [self.region],
                            'TargetLocationMaxConcurrency': self.target_location_max_concurrency,
                            'TargetLocationMaxErrors': self.target_location_max_errors,
                            'ExecutionRoleName': self.execution_role_name
                        }
                    ]                    
                )                     
            else:
                parms = {
                        'automationAssumeRole': [f'arn:aws:iam::{self.accounts_id}:role/{self.asg_execution_role_name}'],
                        'sourceAMIid' : [image_id[i]],
                        'subnetId' : [subnet_id[i]],
                        'targetASG' : [asg_name[i]],
                        'instanceProfileRoleName' : [self.profile_role_name],
                        'updateASGLambdaName': [self.lambda_name],
                        'retainHealthyPercentage': [self.retain_healthy_percentage],
                        'refreshASGInstances': [self.refresh_asg_instances],
                        'instancesEnvironmentTag': [self.env],
                        'securitygroupId': [sg_id[i]]
                    }
                if len(self.run_patch_baseline_install_override_list) > 0:
                    parms['installOverrideList'] = [self.run_patch_baseline_install_override_list]

                response = self.ssm_client.start_automation_execution(
                    DocumentName=f'{self.asg_document_name}',
                    Parameters=parms,
                    TargetLocations=[
                        {
                            'Accounts': [self.accounts_id],
                            'Regions': [self.region],
                            'TargetLocationMaxConcurrency': self.target_location_max_concurrency,
                            'TargetLocationMaxErrors': self.target_location_max_errors,
                            'ExecutionRoleName': self.execution_role_name
                        }
                    ]                    
                )

    def patch_asg(self):
        try:
            for region in self.regions:
                self.ec2_client = boto3.client('ec2',region_name=region)
                self.as_client = boto3.client('autoscaling',region_name=region)
                self.ssm_client = boto3.client('ssm',region_name=self.patching_template_region)
                self.region = region
                [asgs, subnets, images, sgs] = self.describe_asg(self.env)
                self.invoke_ssm_doc(asgs, subnets, images, sgs)
        except Exception as exp:
            print(str(exp))

def lambda_handler(event,context):
    try:
        patching_asg = PatchingASG(event,context)
        patching_asg.patch_asg()

    except Exception as exp:
        print(str(exp))
            

