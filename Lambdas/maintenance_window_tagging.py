# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import boto3
from datetime import datetime
import logging
from crhelper import CfnResource
import os
from boto3.session import Session

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)
CH = logging.StreamHandler()
CH.setLevel(logging.INFO)
FORMATTER = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
CH.setFormatter(FORMATTER)
LOGGER.addHandler(CH)

helper = CfnResource()

class TagInstances(object):
    """
    # Class: TagInstances
    # Description: Tagging instances in the child account
    """

    def __init__(self, event, context):
        self.event = event
        self.context = context
        self.exception = []
        try:
            regions = os.environ["WORKLOAD_REGIONS"]
            self.regions = regions.split(",")            
            resource_properties = self.event['ResourceProperties']
            self.env = resource_properties['Environment']
            self.supported_state_list = ['running'] #,'stopped','terminated']
            self.supported_env_list = [self.env] # to add var
            self.include_asg = resource_properties['IncludeASG']
            self.supported_asg_list = ['null']
            self.supported_patch_list = ['null']            
            self.supported_eks_list = ['null']            
            self.tag_list =  [{'Key': 'Patch Group','Value': self.env},{'Key': 'maintenance_window','Value': self.env+'_maintenance_window'}]                        
            print("resource_properties", resource_properties)
        except Exception as exception:
            self.reason_data = "Missing required property %s" % exception
            LOGGER.error(self.reason_data)
            print("Failed in except block of __init__")
        # session = Session()
        # self.regions = session.get_available_regions('ec2')
        # print(self.regions)

    def get_instance_list(self):      
        try:
            response = self.ec2_client.describe_instances(
                            DryRun=False,
                            MaxResults=1000,
                            Filters=[
                                {
                                    'Name': 'tag:environment',
                                    'Values': [self.env]
                                }
                            ])
            instance_list_tmp = [r['Instances'] for r in response['Reservations']]
            in_list = [val for sublist in instance_list_tmp for val in sublist]    
            return in_list
        except Exception as exception:
            message = 'no instances in account '+str(exception)
            print(message)
            in_list = 'empty'
            return in_list

    def get_image_name(self,image_id):      
        try:
            response = self.ec2_client.describe_images(
                            DryRun=False,
                            ImageIds=image_id,
                            IncludeDeprecated=True)
            image_name = response['Images'][0]['Name']
            return image_name
        except Exception as exception:
            print(str(exception))
            self.exception.append(str(exception))
            raise Exception(str(exception))

    def build_instance_list(self, in_list):
        instance_id = []
        instance_state = []
        instance_tags = []  
        for i in in_list:
            instance_id.append(i['InstanceId'])
            instance_state.append(i['State']['Name'])
            instance_tags.append(i['Tags'])
        
        instance_tag_asg = []
        instance_tag_patch = []
        instance_tag_eks = []

        for tags in instance_tags:
            tag_key_tmp = [r['Key'] for r in tags]
            tag_value_tmp = [r['Value'] for r in tags]
            try:
                i = tag_key_tmp.index('aws:autoscaling:groupName')
                instance_tag_asg.append(tag_value_tmp[i])
            except:
                instance_tag_asg.append('null')
            try:
                i = tag_key_tmp.index('install_patch')
                if tag_value_tmp[i]!='no' or tag_value_tmp[i]!='No':
                    instance_tag_patch.append('null')
                elif tag_value_tmp[i]=='no' or tag_value_tmp[i]=='No':
                    instance_tag_patch.append(tag_value_tmp[i])
            except:
                instance_tag_patch.append('null')
            try:
                i = tag_key_tmp.index('Alpha.eksctl.io/nodegroup-name')
                instance_tag_eks.append(tag_value_tmp[i])
            except:
                instance_tag_eks.append('null')

        return instance_id, instance_state, instance_tag_asg, instance_tag_patch, instance_tag_eks

    def filter_list(self, tmp_list, filter_list):
        filtered_list_indices=[]
        for i in range(0, len(tmp_list)) :
            if tmp_list[i] in filter_list:
                filtered_list_indices.append(i)
        return filtered_list_indices

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


    def tag_instances_main(self):
        try:
            for region in self.regions:
                self.ec2_client = boto3.client('ec2',region_name=region)
                self.as_client = boto3.client('autoscaling',region_name=region)                
                instance_list = self.get_instance_list()
                if instance_list != 'empty':
                    [instance_id, instance_state, instance_tag_asg, instance_tag_patch, instance_tag_eks] = self.build_instance_list(instance_list)

                    ind_state = self.filter_list(instance_state, self.supported_state_list)
                    ind_patch = self.filter_list(instance_tag_patch, self.supported_patch_list)
                    ind_asg = self.filter_list(instance_tag_asg, self.supported_asg_list)
                    ind_eks = self.filter_list(instance_tag_eks, self.supported_eks_list)

                    ind_state_patch = list(set(ind_state).intersection(ind_patch))
                    ind_state_patch_asg = list(set(ind_state_patch).intersection(ind_asg))
                    ind_state_patch_asg_eks = list(set(ind_state_patch_asg).intersection(ind_eks))
                    combined_ind = ind_state_patch_asg_eks
                    
                    filtered_instance_id = [instance_id[i] for i in combined_ind]

                    if self.event['RequestType'] == 'Delete':
                        self.tag_list =  [{'Key': 'Patch Group','Value': 'Default'},{'Key': 'maintenance_window','Value': 'Default_maintenance_window'}]                        
                    response = self.add_tags(filtered_instance_id, self.tag_list)             
            status = "SUCCESS"                
            return status
        except Exception as exp:
            status = "FAILED"                
            return status


    def get_asg_list(self,env):      
        try:
            response = self.as_client.describe_auto_scaling_groups()
            asg_name=[]
            for group in response['AutoScalingGroups']:
                is_eks = False
                for tags in group['Tags']:
                    if tags['Key'] == 'k8s.io/cluster-autoscaler/enabled' and tags['Value'] == 'TRUE':
                        is_eks = True
                if is_eks==False:
                    for tags in group['Tags']:                        
                        if tags['Key'] == 'environment' and tags['Value'] == env:
                            asg_name.append(group['AutoScalingGroupName'])
                                            
            return asg_name

        except Exception as exp:  
            print('No such ASG '+str(exp))


    def tag_asg_main(self):
        try:
            for region in self.regions:
                self.as_client = boto3.client('autoscaling',region_name=region)
                self.ec2_client = boto3.client('ec2',region_name=region)                
                asg_name = self.get_asg_list(self.env)
                env = self.env
                if self.event['RequestType'] == 'Delete':
                    env = 'Default'
                for filtered_asg_name in asg_name:
                    print(filtered_asg_name)    
                    response = self.as_client.create_or_update_tags(
                        Tags=[
                            {
                                'ResourceId': filtered_asg_name,
                                'ResourceType': 'auto-scaling-group',
                                'Key': 'Patch Group',
                                'Value': env,
                                'PropagateAtLaunch': False
                            },        
                            {
                                'ResourceId': filtered_asg_name,
                                'ResourceType': 'auto-scaling-group',
                                'Key': 'maintenance_window',
                                'Value': env+'_maintenance_window',
                                'PropagateAtLaunch': False
                            }
                        ]
                    )
            status = "SUCCESS"                
            return status
        except Exception as exp:
            status = "FAILED"                
            return status            


@helper.create
@helper.update
@helper.delete
def instance_asg_tagging_main(event, context):
    tag_instances = TagInstances(event,context)
    if event['RequestType'] == 'Delete':
        status  = tag_instances.tag_instances_main()
        if status=='SUCCESS' and event['ResourceProperties']['IncludeASG'] == 'Yes':
            status = tag_instances.tag_asg_main()
    elif event['RequestType'] in ['Update', 'Create']:
        status  = tag_instances.tag_instances_main()
        if status=='SUCCESS' and event['ResourceProperties']['IncludeASG'] == 'Yes':
            status = tag_instances.tag_asg_main()
    helper.Data['TaggingStatus'] = status

def lambda_handler(event, context):
    helper(event,context)

