# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import boto3
from datetime import datetime, timedelta
import logging
import os
import time
from crhelper import CfnResource

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)
CH = logging.StreamHandler()
CH.setLevel(logging.INFO)
FORMATTER = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
CH.setFormatter(FORMATTER)
LOGGER.addHandler(CH)

helper = CfnResource()

class CreateMaintenanceWindow(object):
    """
    # Class: CreateMaintenanceWindow
    # Description: create maintance window
    """

    def __init__(self, event, context):
        self.event = event
        self.context = context
        self.exception = []
        self.ssm_client = boto3.client('ssm')
        self.lambda_arn = os.environ["MW_TASK_LAMBDA_ARN"] 
        self.asg_lambda_arn = os.environ["MW_ASG_TASK_LAMBDA_ARN"] 
        self.service_role_arn = os.environ["SERVICE_ROLE_ARN"]
        try:        
            self.resource_properties = event['ResourceProperties']
            self.env = self.resource_properties['Environment']
            self.frequency = int(self.resource_properties['PatchingFrequency'])
            self.weekday = self.resource_properties['PatchingWindowWeekday']
            self.start_time = self.resource_properties['PatchingWindowStartTime']
            self.duration = self.resource_properties['PatchingWindowDuration']
            self.include_asg = self.resource_properties['IncludeASG']
            self.retain_healthy_percentage = self.resource_properties['RetainHealthyPercentage']
            self.refresh_asg_instances = self.resource_properties['RefreshASGInstances']
            self.patching_operation = self.resource_properties['PatchingOperation']
            self.operation_post_patching = self.resource_properties['OperationPostPatching']
            print("resource_properties", self.resource_properties)
        except Exception as exception:
            self.reason_data = "Missing required property %s" % exception
            LOGGER.error(self.reason_data)
            print("Failed in except block of __init__")
            

    def create_maintenance_window_call(self,env,frequency,weekday,start_time,duration): 
        day_int = time.strptime(weekday, "%A").tm_wday
        delta_to_start_day = timedelta( (day_int - datetime.now().weekday()) % 7 )
        if str(delta_to_start_day) == '0:00:00':
            delta_to_start_day = timedelta( (day_int - datetime.now().weekday() ) % 7 ) + timedelta(days=7)
        start_day = datetime.now() + delta_to_start_day
        d_string = start_day.strftime("%Y-%m-%d")
        start_time = d_string+'T'+start_time+':00:00Z' 
        window_id = 'Not created'
        try:
            response = self.ssm_client.create_maintenance_window(
                Name=env+'_maintenance_window',
                Schedule='rate({} days)'.format(frequency),
                StartDate=start_time,
                ScheduleTimezone='UTC',
                Duration=duration,
                Cutoff=1,
                AllowUnassociatedTargets=True,
            )
            window_id = response['WindowId']
            payload = {
                            "env": self.env,
                            "include_asg": self.include_asg,
                            "retain_healthy_percentage": self.retain_healthy_percentage,
                            "patching_operation": self.patching_operation,
                            "operation_post_patching": self.operation_post_patching,
                            "run_patch_baseline_install_override_list": ""                            
                            }
            response = self.ssm_client.register_task_with_maintenance_window(
                WindowId=window_id,
                TaskArn=self.lambda_arn,
                ServiceRoleArn=self.service_role_arn,
                TaskType='LAMBDA',
                TaskInvocationParameters={
                    'Lambda': {
                        'Payload': json.dumps(payload)
                    }
                })

            if self.include_asg == 'Yes':
                asg_payload = {
                                "env": self.env,
                                "include_asg": self.include_asg,
                                "retain_healthy_percentage": self.retain_healthy_percentage,
                                "refresh_asg_instances": self.refresh_asg_instances,
                                "patching_operation": self.patching_operation,
                                "operation_post_patching": self.operation_post_patching,
                                "run_patch_baseline_install_override_list": ""                            
                                }
                response = self.ssm_client.register_task_with_maintenance_window(
                    WindowId=window_id,
                    TaskArn=self.asg_lambda_arn,
                    ServiceRoleArn=self.service_role_arn,
                    TaskType='LAMBDA',
                    TaskInvocationParameters={
                        'Lambda': {
                            'Payload': json.dumps(asg_payload)
                        }
                    })
                        
            status = "SUCCESS"
            return status, window_id    
        except Exception as exp:  
            status = "FAILED"
            return status, window_id      

    def delete_maintenance_window_call(self,env): 
        try:
            response = self.ssm_client.describe_maintenance_windows(
                Filters=[{'Key': 'Name', 'Values': [env+'_maintenance_window']}]
            )
            for window in response['WindowIdentities']:
                window_id = window['WindowId']
                response = self.ssm_client.delete_maintenance_window(
                    WindowId=window_id
                )
            status = "SUCCESS"
            return status        
        except Exception as exp:  
            status = "FAILED"
            return status      


@helper.create
@helper.update
@helper.delete
def maintenance_main(event,context):
    maintenance_window = CreateMaintenanceWindow(event,context)
    env = event['ResourceProperties']['Environment']
    frequency = event['ResourceProperties']['PatchingFrequency']
    weekday = event['ResourceProperties']['PatchingWindowWeekday']
    start_time = event['ResourceProperties']['PatchingWindowStartTime']
    duration = int(event['ResourceProperties']['PatchingWindowDuration'])
    if event['RequestType'] == 'Delete':
        status = maintenance_window.delete_maintenance_window_call(env)
    elif event['RequestType'] == 'Update':
        old_env = event['OldResourceProperties']['Environment']
        status = maintenance_window.delete_maintenance_window_call(old_env)
        if status == 'SUCCESS':
            [status, window_id] = maintenance_window.create_maintenance_window_call(env,frequency,weekday,start_time,duration)
            helper.Data['WindowId'] = window_id
    elif event['RequestType'] == 'Create':
        [status, window_id] = maintenance_window.create_maintenance_window_call(env,frequency,weekday,start_time,duration)
        helper.Data['WindowId'] = window_id
    if status =='FAILED':
        raise Exception(str(status))


def lambda_handler(event,context):
    helper(event,context)

