# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import datetime
import time
import boto3

print('Loading function')


def lambda_handler(event, context):
    print("Received event: " + json.dumps(event, indent=2))

    target_asg = event['targetASG']
    new_ami_id = event['newAmiID']
    retain_healthy_percentage = event['retainHealthyPercentage']
    refresh_asg_instances = event['refreshASGInstances']
    # get autoscaling client
    client = boto3.client('autoscaling')

    # get object for the ASG we're going to update, filter by name of target ASG
    response = client.describe_auto_scaling_groups(AutoScalingGroupNames=[target_asg])

    if not response['AutoScalingGroups']:
        return 'No such ASG'

    # get name of InstanceID in current ASG that we'll use to model new Launch Configuration after
    sourceInstanceId = response.get('AutoScalingGroups')[0]['Instances'][0]['InstanceId']

    # create LC using instance from target ASG as a template, only diff is the name of the new LC and new AMI
    timeStamp = time.time()
    timeStampString = datetime.datetime.fromtimestamp(timeStamp).strftime('%Y-%m-%d  %H-%M-%S')
    newLaunchConfigName = 'LC '+ new_ami_id + ' ' + timeStampString
    client.create_launch_configuration(
        InstanceId = sourceInstanceId,
        LaunchConfigurationName=newLaunchConfigName,
        ImageId= new_ami_id )

    # update ASG to use new LC
    response = client.update_auto_scaling_group(AutoScalingGroupName = target_asg,LaunchConfigurationName = newLaunchConfigName)
    
    if refresh_asg_instances == 'Yes':
        response = client.start_instance_refresh(
            AutoScalingGroupName=target_asg,
            Strategy='Rolling',
            Preferences={
                'MinHealthyPercentage': int(retain_healthy_percentage),
                'InstanceWarmup': 120
            })
    
    return 'Updated ASG `%s` with new launch configuration `%s` which includes AMI `%s`.' % (event['targetASG'], newLaunchConfigName, new_ami_id)