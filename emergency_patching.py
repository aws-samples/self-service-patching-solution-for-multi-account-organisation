

import boto3
import json
import os
import random
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)
CH = logging.StreamHandler()
CH.setLevel(logging.INFO)
FORMATTER = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
CH.setFormatter(FORMATTER)
logger.addHandler(CH)

class EmergencyPatching(object):

    def __init__(self, event, context):
        try:
            global session
            session = boto3.session.Session()
            self.organizations_client = session.client('organizations')
            root_ou_id = self.organizations_client.list_roots()
            self.root_ou_id = (root_ou_id['Roots'][0]['Id'])
            self.task_lambda_name = os.environ["TASK_LAMBDA_NAME"] 
            self.asg_task_lambda_name = os.environ["ASG_TASK_LAMBDA_NAME"] 
            self.patching_template_region = os.environ["PATCHING_TEMPLATE_REGION"]
            self.child_account_role = os.environ["CHILD_ACCOUNT_ROLE"]         
            env = event['env']
            self.include_asg=event['include_asg']
            retain_healthy_percentage=event['retain_healthy_percentage']
            patching_operation=event['patching_operation']
            operation_post_patching=event['operation_post_patching']
            run_patch_baseline_install_override_list=event['run_patch_baseline_install_override_list']
            refresh_asg_instances=event['refresh_asg_instances']
            self.taskLambdaPayload = {
                            "env": env,
                            "patching_operation": patching_operation,
                            "operation_post_patching": operation_post_patching,
                            "run_patch_baseline_install_override_list": run_patch_baseline_install_override_list,
                            "include_asg": self.include_asg,
                            "retain_healthy_percentage": retain_healthy_percentage,
                            "refresh_asg_instances": refresh_asg_instances                            
                            }
            print(self.taskLambdaPayload)
        except Exception as exception:
            print("unable to init")
            raise Exception(str(exception))

    def get_accounts(self):
        paginator = self.organizations_client.get_paginator('list_accounts')
        page_iterator = paginator.paginate()
        for page in page_iterator:
            accounts_list = page['Accounts']
            for account in accounts_list:
                try:
                    account_id = account['Id']
                    if account['Status'] == "ACTIVE":
                        self.assume_role(account_id)
                        lambda_client_child = self.assumeRoleSession.client('lambda', region_name=self.patching_template_region)
                        response = lambda_client_child.invoke(FunctionName=self.task_lambda_name,
                                                        Payload=json.dumps(self.taskLambdaPayload), InvocationType='Event')
                        if self.include_asg=='Yes':
                            response = lambda_client_child.invoke(FunctionName=self.asg_task_lambda_name,
                                                            Payload=json.dumps(self.taskLambdaPayload), InvocationType='Event')
                except Exception as exception:
                    print(exception)

    def assume_role(self, child_account_id):
        account_number = child_account_id
        secondary_rolearn = "arn:aws:iam::{}:role/{}".format(account_number,self.child_account_role)
        secondary_session_name = "SecondarySession-" + str(random.randint(1, 100000))
        sts_client = session.client('sts')
        # Logging to child account.
        secondaryRoleCreds = sts_client.assume_role(RoleArn=secondary_rolearn,
                                                            RoleSessionName=secondary_session_name)
        credentials = secondaryRoleCreds.get('Credentials')
        accessKeyID = credentials.get('AccessKeyId')
        secretAccessKey = credentials.get('SecretAccessKey')
        sessionToken = credentials.get('SessionToken')
        self.assumeRoleSession = boto3.session.Session(accessKeyID, secretAccessKey, sessionToken)
        logger.info('Assumed in role in child account {}'.format(account_number))    

def lambda_handler(event, context):
    """
    This is starting point of Lambda execution
    """
    emergency_patching = EmergencyPatching(event, context)
    emergency_patching.get_accounts()