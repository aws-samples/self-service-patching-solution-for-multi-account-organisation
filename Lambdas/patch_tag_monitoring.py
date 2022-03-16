# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import boto3
from datetime import datetime
import logging
import os

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)
CH = logging.StreamHandler()
CH.setLevel(logging.INFO)
FORMATTER = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
CH.setFormatter(FORMATTER)
LOGGER.addHandler(CH)

class TagInstances(object):
    """
    # Class: TagInstances
    # Description: Tagging instances in the child account
    """
    def __init__(self, event, context):
        self.event = event
        self.context = context
        self.ec2_client = boto3.client('ec2')
        self.as_client = boto3.client('autoscaling')
        patching_template_region = os.environ["PATCHING_TEMPLATE_REGION"]
        self.ssm_client = boto3.client('ssm', region_name=patching_template_region)
        try:
            self.supported_env_list = ['Default','Dev','Test','Prod'] 
            self.supported_asg_list = ['null']
            self.supported_patch_list = ['null']            
            self.supported_eks_list = ['null']            
        except Exception as exception:
            self.reason_data = "Missing required property %s" % exception
            LOGGER.error(self.reason_data)
            print("Failed in except block of __init__")

    def get_instance_list(self,instance_id):      
        try:
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            try:
                tags = response['Reservations'][0]['Instances'][0]['Tags']
            except:
                tags = 'empty'
            return tags
        except Exception as exception:
            message = 'no instances in account'+str(exception)
            print(message)
            return message

    def build_instance_list(self, instance_tags): 
        instance_tag_env = []
        instance_tag_asg = []
        instance_tag_patch = []
        instance_tag_eks = []
        tag_key_tmp = [r['Key'] for r in instance_tags]
        tag_value_tmp = [r['Value'] for r in instance_tags]
        try:
            i = tag_key_tmp.index('environment')
            instance_tag_env.append(tag_value_tmp[i])
            self.env = tag_value_tmp[i]
        except:
            instance_tag_env.append('null')
            self.env = 'null'
        try:
            i = tag_key_tmp.index('aws:autoscaling:groupName')
            instance_tag_asg.append(tag_value_tmp[i])
        except:
            instance_tag_asg.append('null')
        try:
            i = tag_key_tmp.index('install_patch')
            if tag_value_tmp[i]=='no' or tag_value_tmp[i]=='No':
                instance_tag_patch.append(tag_value_tmp[i])
            else:
                instance_tag_patch.append('null')
        except:
            instance_tag_patch.append('null')
        try:
            i = tag_key_tmp.index('Alpha.eksctl.io/nodegroup-name')
            instance_tag_eks.append(tag_value_tmp[i])
        except:
            instance_tag_eks.append('null')

        return instance_tag_env, instance_tag_asg, instance_tag_patch, instance_tag_eks

    def add_tags(self, id_list, tag_list):
        try:
            response = self.ec2_client.create_tags(
                DryRun=False,
                Resources=id_list,
                Tags=tag_list
                )
            return response
        except Exception as exception:
            message = 'no instances to tag' +str(exception)
            print(message)
            return message  

    def check_mw(self,env):
        response = self.ssm_client.describe_maintenance_windows(
                Filters=[{'Key': 'Name', 'Values': [env+'_maintenance_window']}]
            )
        try:
            mw_name = response['WindowIdentities'][0]['Name']
            print('Found ' +mw_name)
            return True
        except:
            print('No maintenace window for environment ' + env)
            return False

    def tag_instances_main(self,instance_id):
        try:
            tags = self.get_instance_list(instance_id)
            if tags != 'empty':
                [instance_tag_env, instance_tag_asg, instance_tag_patch, instance_tag_eks] = self.build_instance_list(tags)
                if any(s in instance_tag_patch for s in self.supported_patch_list) and any(s in instance_tag_asg for s in self.supported_asg_list) and any(s in instance_tag_eks for s in self.supported_eks_list):
                    if self.check_mw(self.env):
                        tag_list =  [{'Key': 'Patch Group','Value': self.env},{'Key': 'maintenance_window','Value': self.env+'_maintenance_window'}]
                    elif (self.env in self.supported_env_list):
                        tag_list =  [{'Key': 'Patch Group','Value': 'Default'},{'Key': 'maintenance_window','Value': 'Default_maintenance_window'}]
                    else:
                        tag_list =  [{'Key': 'environment','Value': 'Default'},{'Key': 'Patch Group','Value': 'Default'},{'Key': 'maintenance_window','Value': 'Default_maintenance_window'}]
                response = self.add_tags([instance_id], tag_list)
                
            else:
                tag_list =  [{'Key': 'environment','Value': 'Default'},{'Key': 'Patch Group','Value': 'Default'},{'Key': 'maintenance_window','Value': 'Default_maintenance_window'}]
            response = self.add_tags([instance_id], tag_list)

        except Exception as exp:
            print(str(exp))

    def get_asg_list(self,target_asg):
        try:
            response = self.as_client.describe_auto_scaling_groups(AutoScalingGroupNames=[target_asg])
            exempt = False
            for tags in response['AutoScalingGroups'][0]['Tags']:
                if (tags['Key'] == 'k8s.io/cluster-autoscaler/enabled' and tags['Value'] == 'TRUE') or (tags['Key'] == 'install_patch' and tags['Value'] == 'no'):
                    exempt = True
            if exempt==False:
                self.env = 'null'
                for tags in response['AutoScalingGroups'][0]['Tags']:                       
                    if tags['Key'] == 'environment' and tags['Value'] in self.supported_env_list:
                        self.env = tags['Value']
                     
            return exempt


        except Exception as exp:  
            print('No such ASG '+str(exp))

    def tag_asg_main(self,asg_name):
        try:
            exempt = self.get_asg_list(asg_name)
            if exempt == False:
                if self.check_mw(self.env):
                    response = self.as_client.create_or_update_tags(
                        Tags=[
                            {
                                'ResourceId': asg_name,
                                'ResourceType': 'auto-scaling-group',
                                'Key': 'Patch Group',
                                'Value': self.env,
                                'PropagateAtLaunch': False
                            },       
                            {
                                'ResourceId': asg_name,
                                'ResourceType': 'auto-scaling-group',
                                'Key': 'maintenance_window',
                                'Value': self.env+'_maintenance_window',
                                'PropagateAtLaunch': False
                            }
                        ]
                    )
                elif (self.env in self.supported_env_list):
                    response = self.as_client.create_or_update_tags(
                        Tags=[
                            {
                                'ResourceId': asg_name,
                                'ResourceType': 'auto-scaling-group',
                                'Key': 'Patch Group',
                                'Value': 'Default',
                                'PropagateAtLaunch': False
                            },       
                            {
                                'ResourceId': asg_name,
                                'ResourceType': 'auto-scaling-group',
                                'Key': 'maintenance_window',
                                'Value': 'Default_maintenance_window',
                                'PropagateAtLaunch': False
                            }
                        ]
                    )
                else:
                    response = self.as_client.create_or_update_tags(
                        Tags=[
                            {
                                'ResourceId': asg_name,
                                'ResourceType': 'auto-scaling-group',
                                'Key': 'environment',
                                'Value': 'Default',
                                'PropagateAtLaunch': False
                            },                           
                            {
                                'ResourceId': asg_name,
                                'ResourceType': 'auto-scaling-group',
                                'Key': 'Patch Group',
                                'Value': 'Default',
                                'PropagateAtLaunch': False
                            },       
                            {
                                'ResourceId': asg_name,
                                'ResourceType': 'auto-scaling-group',
                                'Key': 'maintenance_window',
                                'Value': 'Default_maintenance_window',
                                'PropagateAtLaunch': False
                            }
                        ]
                    )
        except Exception as exp:
            print(str(exp))            

def lambda_handler(event, context):
    tag_instances = TagInstances(event,context)
    resourceType = event['detail']['resourceType'].split("::")[1]
    if resourceType == 'EC2':
        print("Given resourceType is EC2")
        instance_id = event['detail']['resourceId']
        tag_instances.tag_instances_main(instance_id)
    elif resourceType == 'AutoScaling':
        print("Given resourceType is AutoScaling ")
        asg_name = event['detail']['resourceId'].split("/")[1]
        tag_instances.tag_asg_main(asg_name)
