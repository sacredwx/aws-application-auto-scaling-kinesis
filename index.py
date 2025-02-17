import boto3
import json
import os

client_kinesis = boto3.client('kinesis')
client_ssm = boto3.client('ssm')
client_cloudwatch = boto3.client('cloudwatch')
client_lambda = boto3.client('lambda')
client_cloudformation = boto3.client('cloudformation')

PARAMETER_STORE = os.environ['ParameterStore']
AUTOSCALINGPOLICYOUT_ARN = ''
AUTOSCALINGPOLICYIN_ARN = ''
CLOUDWATCHALARMNAMEOUT = os.environ['CloudWatchAlarmNameOut']
CLOUDWATCHALARMNAMEIN = os.environ['CloudWatchAlarmNameIn']
CLOUDWATCHALARMNAMEOUT2 = os.environ['CloudWatchAlarmNameOut2']
CLOUDWATCHALARMNAMEIN2 = os.environ['CloudWatchAlarmNameIn2']
CLOUDWATCHALARMNAMEOUT3 = os.environ['CloudWatchAlarmNameOut3']


def update_shards(desiredCapacity, resourceName, scaleOut: bool):
    print("Action: "+("Scale-Out" if scaleOut else "Scale-In")+" to "+str(desiredCapacity))

    if scaleOut == False and all_metrics_can_scale_in() == False:
        print("Scale-In Denied")
        return "Denied"

    # Update the shard count to the new Desired Capacity value
    try:
        response = client_kinesis.update_shard_count(
            StreamName=resourceName,
            TargetShardCount=int(desiredCapacity),
            ScalingType='UNIFORM_SCALING'
        )
        print("Response: ", response)
        scalingStatus = "InProgress"

        # need also to update alarm threshold using the put_metric_alarm
        update_alarm_out(desiredCapacity, resourceName)
        update_alarm_in(desiredCapacity, resourceName)

    # In case of error of updating the sharding, raise an exception. Possible cause, you cannot reshard more than twice a day
    except Exception as e:
        print(e)
        failureReason = str(e)
        scalingStatus = "Failed"
        pass

    return scalingStatus


# fuction to update scale out alarm threshold
def update_alarm_out(shards, stream):
    try:
        client_cloudwatch.put_metric_alarm(
            AlarmName=CLOUDWATCHALARMNAMEOUT,
            AlarmDescription='incomingRecord exceeds threshold',
            MetricName='IncomingRecords',
            Namespace='AWS/Kinesis',
            Dimensions=[
                {
                    'Name': 'StreamName',
                    'Value': stream
                }
            ],
            Statistic='Sum',
            Period=60,
            EvaluationPeriods=1,
            Threshold=(1000 * int(shards) * 60)*80/100,
            ComparisonOperator='GreaterThanThreshold',
            AlarmActions=[
                AUTOSCALINGPOLICYOUT_ARN
            ]
        )
        client_cloudwatch.put_metric_alarm(
            AlarmName=CLOUDWATCHALARMNAMEOUT2,
            AlarmDescription='IncomingBytes exceeds threshold',
            MetricName='IncomingBytes',
            Namespace='AWS/Kinesis',
            Dimensions=[
                {
                    'Name': 'StreamName',
                    'Value': stream
                }
            ],
            Statistic='Sum',
            Period=60,
            EvaluationPeriods=1,
            Threshold=(1000000 * int(shards) * 60)*80/100,
            ComparisonOperator='GreaterThanThreshold',
            AlarmActions=[
                AUTOSCALINGPOLICYOUT_ARN
            ]
        )
        client_cloudwatch.put_metric_alarm(
            AlarmName=CLOUDWATCHALARMNAMEOUT3,
            AlarmDescription='WriteProvisionedThroughputExceeded exceeds threshold',
            MetricName='WriteProvisionedThroughputExceeded',
            Namespace='AWS/Kinesis',
            Dimensions=[
                {
                    'Name': 'StreamName',
                    'Value': stream
                }
            ],
            Statistic='Sum',
            Period=60,
            EvaluationPeriods=1,
            Threshold=0,  # WriteProvisionedThroughputExceeded has a constant threshold
            ComparisonOperator='GreaterThanThreshold',
            AlarmActions=[
                AUTOSCALINGPOLICYOUT_ARN
            ]
        )
    except Exception as e:
        print(e)

# fuction to update scale in alarm threshol


def update_alarm_in(shards, stream):
    try:
        client_cloudwatch.put_metric_alarm(
            AlarmName=CLOUDWATCHALARMNAMEIN,
            AlarmDescription='incomingRecord below threshold',
            MetricName='IncomingRecords',
            Namespace='AWS/Kinesis',
            Dimensions=[
                {
                    'Name': 'StreamName',
                    'Value': stream
                }
            ],
            Statistic='Sum',
            Period=300,
            EvaluationPeriods=3,
            Threshold=(1000 * (int(shards)-1) * 60)*80/100,
            ComparisonOperator='LessThanThreshold',
            AlarmActions=[
                AUTOSCALINGPOLICYIN_ARN
            ]
        )
        client_cloudwatch.put_metric_alarm(
            AlarmName=CLOUDWATCHALARMNAMEIN2,
            AlarmDescription='IncomingBytes below threshold',
            MetricName='IncomingBytes',
            Namespace='AWS/Kinesis',
            Dimensions=[
                {
                    'Name': 'StreamName',
                    'Value': stream
                }
            ],
            Statistic='Sum',
            Period=300,
            EvaluationPeriods=3,
            Threshold=(1000000 * (int(shards)-1) * 60)*80/100,
            ComparisonOperator='LessThanThreshold',
            AlarmActions=[
                AUTOSCALINGPOLICYIN_ARN
            ]
        )
    except Exception as e:
        print(e)


def all_metrics_can_scale_in():
    response = client_cloudwatch.describe_alarms(
        AlarmNames=[
            CLOUDWATCHALARMNAMEIN,
            CLOUDWATCHALARMNAMEIN2,
        ]
    )
    print(response)
    for alarm in response['MetricAlarms']:
        if alarm['StateValue'] == 'OK':
            return False
    return True


def response_function(status_code, response_body):
    return_json = {
        'statusCode': status_code,
        'body': json.dumps(response_body) if response_body else json.dumps({}),
        'headers': {
            'Content-Type': 'application/json',
        },
    }
    # log response
    print(return_json)
    return return_json

# trick for updating environment variable with application autoscaling arn (need to update all the current variables)


def autoscaling_policy_arn(context):
    print(context.function_name)
    function_name = context.function_name
    print(context.invoked_function_arn)
    tags = client_lambda.list_tags(
        Resource=context.invoked_function_arn
    )

    print(tags)
    stack_name = tags['Tags']['aws:cloudformation:stack-name']
    print(stack_name)

    response = client_cloudformation.describe_stack_resources(
        StackName=stack_name,
        LogicalResourceId='AutoScalingPolicyOut'
    )

    AutoScalingPolicyOut = response['StackResources'][0]['PhysicalResourceId']
    print('Autoscaling Policy Out: ' + AutoScalingPolicyOut)
    response2 = client_cloudformation.describe_stack_resources(
        StackName=stack_name,
        LogicalResourceId='AutoScalingPolicyIn'
    )

    AutoScalingPolicyIn = response2['StackResources'][0]['PhysicalResourceId']
    print('Autoscaling Policy In: ' + AutoScalingPolicyIn)

    response = client_lambda.update_function_configuration(
        FunctionName=function_name,
        Timeout=3,
        Environment={
            'Variables': {
                'AutoScalingPolicyOut': AutoScalingPolicyOut,
                'AutoScalingPolicyIn': AutoScalingPolicyIn,
                'ParameterStore': PARAMETER_STORE,
                'CloudWatchAlarmNameOut': CLOUDWATCHALARMNAMEOUT,
                'CloudWatchAlarmNameIn': CLOUDWATCHALARMNAMEIN,
                'CloudWatchAlarmNameOut2': CLOUDWATCHALARMNAMEOUT2,
                'CloudWatchAlarmNameIn2': CLOUDWATCHALARMNAMEIN2,
                'CloudWatchAlarmNameOut3': CLOUDWATCHALARMNAMEOUT3
            }
        }
    )
    print(response)
    return


def lambda_handler(event, context):

    # log the event
    print(json.dumps(event))

    # get Stream name
    if 'scalableTargetDimensionId' in event['pathParameters']:
        resourceName = event['pathParameters']['scalableTargetDimensionId']
        print(resourceName)
    else:
        message = "Error, scalableTargetDimensionId not found"
        return response_function(400, str(message))

    # try to get information of the Kinesis stream
    try:
        response = client_kinesis.describe_stream_summary(
            StreamName=resourceName,
        )
        print(response)
        streamStatus = response['StreamDescriptionSummary']['StreamStatus']
        shardsNumber = response['StreamDescriptionSummary']['OpenShardCount']
        actualCapacity = shardsNumber
    except Exception as e:
        message = "Error, cannot find a Kinesis stream called " + resourceName
        return response_function(404, message)

    # try to retrive the desired capacity from ParameterStore
    response = client_ssm.get_parameter(
        Name=PARAMETER_STORE
    )
    print(response)
    if 'Parameter' in response:
        if 'Value' in response['Parameter']:
            desiredCapacity = response['Parameter']['Value']
            print(desiredCapacity)
    else:
        # if I do not have an entry in ParameterStore, I assume that the desiredCapacity is like the actualCapacity
        desiredCapacity = actualCapacity

    if streamStatus == "UPDATING":
        scalingStatus = "InProgress"
    elif streamStatus == "ACTIVE":
        scalingStatus = "Successful"

    if event['httpMethod'] == "PATCH":
        # Check whether autoscaling is calling to change the Desired Capacity
        if 'desiredCapacity' in event['body']:
            desiredCapacityBody = json.loads(event['body'])
            desiredCapacityBody = desiredCapacityBody['desiredCapacity']

            # Check whether the new desired capacity is negative. If so, I need to calculate the new desired capacity
            if int(desiredCapacityBody) >= 0:
                desiredCapacity = desiredCapacityBody

                # Store the new desired capacity in a ParamenterStore
                response = client_ssm.put_parameter(
                    Name=PARAMETER_STORE,
                    Value=str(int(desiredCapacity)),
                    Type='String',
                    Overwrite=True
                )
                print(response)
                print("Trying to set capacity to " + str(desiredCapacity))

                global AUTOSCALINGPOLICYOUT_ARN
                global AUTOSCALINGPOLICYIN_ARN
                if 'AutoScalingPolicyOut' and 'AutoScalingPolicyIn' not in os.environ:
                    autoscaling_policy_arn(context)
                AUTOSCALINGPOLICYOUT_ARN = os.environ['AutoScalingPolicyOut']
                AUTOSCALINGPOLICYIN_ARN = os.environ['AutoScalingPolicyIn']

                scalingStatus = update_shards(
                    desiredCapacity, resourceName, float(desiredCapacity) > float(actualCapacity))

    if scalingStatus == "Successful" and float(desiredCapacity) != float(actualCapacity):
        scalingStatus = update_shards(
            desiredCapacity, resourceName, float(desiredCapacity) > float(actualCapacity))

    returningJson = {
        "actualCapacity": float(actualCapacity),
        "desiredCapacity": float(desiredCapacity),
        "dimensionName": resourceName,
        "resourceName": resourceName,
        "scalableTargetDimensionId": resourceName,
        "scalingStatus": scalingStatus,
        "version": "0.1.0"
    }

    try:
        returningJson['failureReason'] = failureReason
    except:
        pass

    print(returningJson)

    return response_function(200, returningJson)
