import boto3
import json
import sys
from datetime import datetime


class DateTimeEncoder(json.JSONEncoder):
    """
    Custom JSON encoder for handling datetime objects.
    """
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()  # Convert datetime to ISO format
        return super().default(obj)


def find_team_cluster(team_tag_key='ApplicationShortName', team_tag_value=''):
    """
    Finds all ECS cluster ARNs for a given ApplicationShortName tag value.
    """
    ecs_client = boto3.client(service_name='ecs', region_name='us-east-1')
    matching_clusters = []

    try:
        # List all clusters with pagination
        clusters = []
        paginator = ecs_client.get_paginator('list_clusters')
        for page in paginator.paginate():
            clusters.extend(page.get('clusterArns', []))

        for cluster_arn in clusters:
            # Fetch tags for the cluster
            tags_response = ecs_client.list_tags_for_resource(resourceArn=cluster_arn)
            tags = tags_response.get('tags', [])

            # Check if the cluster has the desired team tag
            for tag in tags:
                if tag['key'] == team_tag_key and tag['value'] == team_tag_value:
                    cluster_name = cluster_arn.split('/')[-1]  # Extract cluster name from ARN
                    matching_clusters.append((cluster_name, cluster_arn))

        if not matching_clusters:
            print(f"No ECS clusters found for {team_tag_key} = {team_tag_value}")
        return matching_clusters
    except Exception as e:
        print(f"Error finding ECS clusters: {e}")
        sys.exit(1)


def load_env_config(env_index):
    """
    Load environment configuration from aws_env_config.json file by index.
    Returns None if file doesn't exist or is empty.
    
    Args:
        env_index: Index of environment to load (0, 1, etc.)
    """
    try:
        with open('aws_env_config.json', 'r') as f:
            content = f.read().strip()
            if not content:
                return None
            config = json.loads(content)
            envs = config.get('envs', [])
            return envs[env_index] if 0 <= env_index < len(envs) else None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def fetch_ecs_service_config(cluster_configs, use_custom_identifier=False):
    """
    Fetches the configuration of ECS services for specified cluster names.
    Returns services with indexed keys.
    """
    ecs_client = boto3.client(service_name='ecs', region_name='us-east-1')
    all_service_configs = {}
    cluster_index = 0

    try:
        for cluster_config in cluster_configs:
            service_index = 0
            cluster_index += 1
            cluster_name = cluster_config['clusterName']
            service_names = cluster_config.get('serviceNames', [])

            # Get cluster ARN
            clusters = ecs_client.list_clusters()['clusterArns']
            cluster_arn = next((arn for arn in clusters if cluster_name in arn), None)
            
            if not cluster_arn:
                print(f"Cluster not found: {cluster_name}")
                continue

            # Fetch services in the cluster with pagination
            services = []
            if service_names:
                services = service_names
            else:
                paginator = ecs_client.get_paginator('list_services')
                for page in paginator.paginate(cluster=cluster_arn):
                    services.extend(page.get('serviceArns', []))

            if not services:
                print(f"No services found in cluster '{cluster_name}'")
                continue

            for service in services:
                service_chunk = [service]
                service_details = ecs_client.describe_services(cluster=cluster_arn, services=service_chunk)
                
                for service_config in service_details['services']:
                    service_index += 1
                    service_config.pop('events', None)
                    service_config.pop('deployments', None)
                    service_name = service_config.get('serviceName')
                    service_key = f"{cluster_name}/{service_name}"
                    
                    # Fetch task definition for the service
                    task_definition_arn = service_config.get('taskDefinition')
                    task_definition = {}
                    if task_definition_arn:
                        task_definition_details = ecs_client.describe_task_definition(taskDefinition=task_definition_arn, include=['TAGS'])
                        task_definition_name = task_definition_details['taskDefinition']['family']
                        container_definitions = task_definition_details['taskDefinition'].pop('containerDefinitions', [])
                        task_definition = {
                            "compareIdentifier": task_definition_name,
                            **task_definition_details['taskDefinition']
                        }
                    
                    # Store with indexed key and include original service key in config
                    if use_custom_identifier:
                        all_service_configs[f"cluster_{cluster_index}/service_{service_index}"] = {
                            "compareIdentifier": service_key,
                            **service_config,
                        }
                        all_service_configs[f"cluster_{cluster_index}/service_{service_index}/task_definition"] = task_definition
                        # Add container definitions to all_service_configs
                        for container_definition in container_definitions:
                            container_name = container_definition["name"]
                            all_service_configs[f"cluster_{cluster_index}/service_{service_index}/task_definition/container_definition/{container_name}"] = {
                                **container_definition
                            }
                    else:
                        all_service_configs[f"{service_key}"] = {
                            **service_config,
                        }
                        all_service_configs[f"{service_key}/task_definition"] = task_definition
                        # Add container definitions to all_service_configs
                        for container_definition in container_definitions:
                            container_name = container_definition["name"]
                            all_service_configs[f"${service_key}{cluster_index}/service_{service_index}/task_definition/container_definition/{container_name}"] = {
                                **container_definition
                            }

        return all_service_configs
    except Exception as e:
        print(f"Error fetching ECS service configurations: {e}")
        sys.exit(1)


def fetch_rds_config(identifier, use_instance_ids=False):
    """
    Fetches RDS configurations either by instance IDs or ApplicationShortName.
    Returns instances with indexed keys or instance names as keys based on mode.
    """
    rds_client = boto3.client('rds', region_name='us-east-1')
    filtered_instances = {}
    instance_index = 0

    try:
        paginator = rds_client.get_paginator('describe_db_instances')
        for page in paginator.paginate():
            for instance in page['DBInstances']:
                should_include = False
                if use_instance_ids:
                    # Using specific instance IDs - use indexed keys
                    should_include = instance['DBInstanceIdentifier'] in identifier
                    if should_include:
                        instance_index += 1
                        instance_id = instance['DBInstanceIdentifier']
                        filtered_instances[f"rds_db_instance_{instance_index}"] = {
                            "compareIdentifier": instance_id,
                            **instance
                        }
                else:
                    # Using ApplicationShortName - use instance names as keys
                    tag_list = instance.get('TagList', [])
                    for tag in tag_list:
                        if tag['Key'] == 'ApplicationShortName' and tag['Value'] == identifier:
                            filtered_instances[instance['DBInstanceIdentifier']] = instance
                            break

        if not filtered_instances:
            print(f"No RDS instances found for {'instance IDs' if use_instance_ids else 'ApplicationShortName'} = {identifier}")

        return filtered_instances
    except Exception as e:
        print(f"Error fetching RDS configurations: {e}")
        sys.exit(1)


def fetch_parameter_store_config(prefixes, use_custom_names=True):
    """
    Fetches Parameter Store configurations under specific prefixes.
    Automatically constructs the full path using the prefixes.
    Returns parameters grouped by prefix.
    """
    ssm_client = boto3.client('ssm', region_name='us-east-1')
    all_parameters = {}
    prefix_index = 0

    for prefix in prefixes:
        prefix_index += 1
        # Remove leading/trailing slashes from the prefix
        prefix = prefix.strip('/')

        # Construct the Parameter Store path
        parameter_path = f'/{prefix}/'
        parameters = []

        try:
            next_token = None
            while True:
                # Pass NextToken only if it has a valid value
                if next_token:
                    response = ssm_client.get_parameters_by_path(Path=parameter_path, Recursive=True, NextToken=next_token)
                else:
                    response = ssm_client.get_parameters_by_path(Path=parameter_path, Recursive=True)

                parameters.extend(response.get('Parameters', []))
                next_token = response.get('NextToken')

                if not next_token:
                    break

            if not parameters:
                print(f"No parameters found under path '{parameter_path}'.")
                if use_custom_names:
                    all_parameters[f"parameter_prefix_{prefix_index}"] = {
                        "compareIdentifier": parameter_path
                    }
                else:
                    all_parameters[parameter_path] = {}
                continue

            # Extract and return parameters as a dictionary, removing the prefix from the parameter names
            if use_custom_names:
                all_parameters[f"parameter_prefix_{prefix_index}"] = {
                    "compareIdentifier": parameter_path,
                    **{param['Name'].replace(parameter_path, '', 1): param['Value'] for param in parameters}
                }
            else:
                all_parameters[parameter_path] = {
                    **{param['Name'].replace(parameter_path, '', 1): param['Value'] for param in parameters}
                }
        except Exception as e:
            print(f"Error fetching Parameter Store configurations for {parameter_path}: {e}")
            if use_custom_names:
                all_parameters[f"parameter_prefix_{prefix_index}"] = {
                    "compareIdentifier": parameter_path
                }
            else:
                all_parameters[parameter_path] = {}

    return all_parameters


def fetch_lambda_config(identifier, use_function_names=False):
    """
    Fetches Lambda function configurations either by function names or ApplicationShortName.
    Returns functions with indexed keys or function names as keys based on the mode.
    """
    lambda_client = boto3.client(service_name='lambda', region_name='us-east-1')
    all_lambda_configs = {}
    function_index = 0

    try:
        if use_function_names:
            # Fetch specific functions by name - use indexed keys
            for function_name in identifier:
                function_index += 1
                try:
                    function_config = lambda_client.get_function(FunctionName=function_name)
                    if 'Code' in function_config:
                        del function_config['Code']
                    
                    all_lambda_configs[f"lambda_function_{function_index}"] = {
                        "compareIdentifier": function_name,
                        **function_config["Configuration"]
                    }
                    
                except lambda_client.exceptions.ResourceNotFoundException:
                    print(f"Lambda function not found: {function_name}")
                    continue
                except Exception as e:
                    print(f"Error fetching configuration for Lambda function {function_name}: {e}")
                    continue
        else:
            # Fetch all functions and filter by ApplicationShortName tag - use function names as keys
            paginator = lambda_client.get_paginator('list_functions')
            for page in paginator.paginate():
                for function in page['Functions']:
                    try:
                        # Get function tags
                        tags_response = lambda_client.list_tags(Resource=function['FunctionArn'])
                        tags = tags_response.get('Tags', {})
                        
                        # Check if function has matching ApplicationShortName tag
                        if tags.get('ApplicationShortName') == identifier:
                            function_config = lambda_client.get_function(FunctionName=function['FunctionName'])
                            if 'Code' in function_config:
                                del function_config['Code']
                            
                            # Use function name as key instead of indexed key
                            all_lambda_configs[function['FunctionName']] = {
                                **function_config["Configuration"]
                            }
                            

                    except Exception as e:
                        print(f"Error processing Lambda function {function['FunctionName']}: {e}")
                        continue

        if not all_lambda_configs:
            print(f"No Lambda functions found for {'function names' if use_function_names else 'ApplicationShortName'} = {identifier}")
            
        return all_lambda_configs
    except Exception as e:
        print(f"Error fetching Lambda configurations: {e}")
        sys.exit(1)


def fetch_elb_config(identifier, use_lb_names=False):
    """
    Fetches the configuration of EC2 load balancers either by load balancer names or ApplicationShortName.
    Returns load balancers with indexed keys or load balancer names as keys based on the mode.
    """
    elb_client = boto3.client('elbv2', region_name='us-east-1')
    all_elb_configs = {}
    elb_index = 0

    try:
        if use_lb_names:
            # Fetch specific load balancers by name - use indexed keys
            for lb_name in identifier:
                elb_index += 1
                try:
                    lb_details = elb_client.describe_load_balancers(Names=[lb_name])
                    for lb_config in lb_details['LoadBalancers']:
                        all_elb_configs[f"elb_{elb_index}"] = {
                            "compareIdentifier": lb_name,
                            **lb_config
                        }
                except elb_client.exceptions.LoadBalancerNotFoundException:
                    print(f"Load balancer not found: {lb_name}")
                    continue
                except Exception as e:
                    print(f"Error fetching configuration for load balancer {lb_name}: {e}")
                    continue
        else:
            # Fetch all load balancers and filter by ApplicationShortName tag - use load balancer names as keys
            paginator = elb_client.get_paginator('describe_load_balancers')
            for page in paginator.paginate():
                for lb in page['LoadBalancers']:
                    try:
                        # Get load balancer tags
                        tags_response = elb_client.describe_tags(ResourceArns=[lb['LoadBalancerArn']])
                        tags = tags_response.get('TagDescriptions', [{}])[0].get('Tags', [])
                        
                        # Check if load balancer has matching ApplicationShortName tag
                        if any(tag['Key'] == 'ApplicationShortName' and tag['Value'] == identifier for tag in tags):
                            all_elb_configs[lb['LoadBalancerName']] = lb

                    except Exception as e:
                        print(f"Error processing load balancer {lb['LoadBalancerName']}: {e}")
                        continue

        if not all_elb_configs:
            print(f"No EC2 load balancers found for {'load balancer names' if use_lb_names else 'ApplicationShortName'} = {identifier}")
            
        return all_elb_configs
    except Exception as e:
        print(f"Error fetching EC2 load balancer configurations: {e}")
        sys.exit(1)


def fetch_sqs_config(queue_names, ApplicationShortName):
    """
    Fetches the configuration of SQS queues for specified queue names.
    Returns queues with indexed keys.
    """
    sqs_client = boto3.client('sqs', region_name='us-east-1')
    all_queue_configs = {}
    queue_index = 0

    try:
        if queue_names:
            for queue_name in queue_names:
                queue_index += 1
                try:
                    queue_url = sqs_client.get_queue_url(QueueName=queue_name)['QueueUrl']
                    queue_attributes = sqs_client.get_queue_attributes(QueueUrl=queue_url, AttributeNames=['All'])['Attributes']
                    all_queue_configs[f"sqs_queue_{queue_index}"] = {
                        "compareIdentifier": queue_name,
                        **queue_attributes
                    }
                except sqs_client.exceptions.QueueDoesNotExist:
                    print(f"SQS queue not found: {queue_name}")
                    continue
                except Exception as e:
                    print(f"Error fetching configuration for SQS queue {queue_name}: {e}")
                    continue
        else:
            # Fetch all SQS queues and filter by ApplicationShortName tag
            list_queues_response = sqs_client.list_queues()
            queue_urls = list_queues_response.get('QueueUrls', [])
            for queue_url in queue_urls:
                try:
                    tags_response = sqs_client.list_queue_tags(QueueUrl=queue_url)
                    tags = tags_response.get('Tags', {})
                    if tags.get('ApplicationShortName') == ApplicationShortName:
                        queue_attributes = sqs_client.get_queue_attributes(QueueUrl=queue_url, AttributeNames=['All'])['Attributes']
                        queue_name = queue_url.split('/')[-1]
                        all_queue_configs[f"{queue_name}"] = {
                            **queue_attributes
                        }
                except Exception as e:
                    print(f"Error processing SQS queue {queue_url}: {e}")
                    continue

        if not all_queue_configs:
            print(f"No SQS queues found for the provided queue names or ApplicationShortName.")
            
        return all_queue_configs
    except Exception as e:
        print(f"Error fetching SQS configurations: {e}")
        sys.exit(1)


def fetch_sns_config(identifier, use_topic_names=False):
    """
    Fetches the configuration of SNS topics either by topic names or ApplicationShortName.
    Returns topics with indexed keys or topic names as keys based on the mode.
    """
    sns_client = boto3.client('sns', region_name='us-east-1')
    all_sns_configs = {}
    topic_index = 0

    try:
        if use_topic_names:
            # Get all topics first to match by name
            all_topics = []
            paginator = sns_client.get_paginator('list_topics')
            for page in paginator.paginate():
                all_topics.extend(page.get('Topics', []))
            
            # Filter topics by the specified names
            for topic_name in identifier:
                topic_index += 1
                # Find the topic ARN that ends with the specified name
                topic_arn = next((t['TopicArn'] for t in all_topics if t['TopicArn'].split(':')[-1] == topic_name), None)
                
                if not topic_arn:
                    print(f"SNS topic not found: {topic_name}")
                    continue
                
                try:
                    # Get comprehensive topic details
                    topic_data = fetch_sns_topic_details(sns_client, topic_arn, topic_name)
                    
                    # Store topic config with all details
                    all_sns_configs[f"sns_topic_{topic_index}"] = {
                        "compareIdentifier": topic_name,
                        **topic_data
                    }
                    
                except Exception as e:
                    print(f"Error fetching configuration for SNS topic {topic_name}: {e}")
                    continue
        else:
            # Fetch all topics and filter by ApplicationShortName tag - use topic names as keys
            paginator = sns_client.get_paginator('list_topics')
            for page in paginator.paginate():
                for topic in page['Topics']:
                    topic_arn = topic['TopicArn']
                    try:
                        # Get topic attributes and tags
                        topic_attributes = sns_client.get_topic_attributes(TopicArn=topic_arn)['Attributes']
                        tags_response = sns_client.list_tags_for_resource(ResourceArn=topic_arn)
                        tags = tags_response.get('Tags', [])
                        
                        # Check if topic has matching ApplicationShortName tag
                        if any(tag['Key'] == 'ApplicationShortName' and tag['Value'] == identifier for tag in tags):
                            # Get topic name from ARN
                            topic_name = topic_arn.split(':')[-1]
                            
                            # Get comprehensive topic details
                            topic_data = fetch_sns_topic_details(sns_client, topic_arn, topic_name)
                            
                            # Use topic name as key instead of indexed key
                            all_sns_configs[topic_name] = topic_data
                            
                    except Exception as e:
                        print(f"Error processing SNS topic {topic_arn}: {e}")
                        continue

        if not all_sns_configs:
            print(f"No SNS topics found for {'topic names' if use_topic_names else 'ApplicationShortName'} = {identifier}")
            
        return all_sns_configs
    except Exception as e:
        print(f"Error fetching SNS configurations: {e}")
        sys.exit(1)


def fetch_sns_topic_details(sns_client, topic_arn, topic_name):
    """
    Helper function to fetch comprehensive details for an SNS topic.
    """
    # Get topic attributes
    topic_attributes = sns_client.get_topic_attributes(TopicArn=topic_arn)['Attributes']
    
    # Get subscriptions for this topic
    subscriptions = []
    subscription_paginator = sns_client.get_paginator('list_subscriptions_by_topic')
    for sub_page in subscription_paginator.paginate(TopicArn=topic_arn):
        subscriptions.extend(sub_page.get('Subscriptions', []))
    
    # Get subscription details, including filter policies
    detailed_subscriptions = []
    for subscription in subscriptions:
        try:
            sub_arn = subscription.get('SubscriptionArn')
            # Skip if subscription is pending confirmation
            if sub_arn == 'PendingConfirmation':
                detailed_subscriptions.append(subscription)
                continue
                
            sub_attributes = sns_client.get_subscription_attributes(SubscriptionArn=sub_arn)['Attributes']
            detailed_subscription = {**subscription, 'Attributes': sub_attributes}
            detailed_subscriptions.append(detailed_subscription)
        except Exception as e:
            print(f"Error fetching details for subscription {subscription.get('SubscriptionArn')}: {e}")
            detailed_subscriptions.append(subscription)
    
    # Get topic tags
    tags_response = sns_client.list_tags_for_resource(ResourceArn=topic_arn)
    tags = tags_response.get('Tags', [])
    
    # Get topic policy from attributes
    policy = None
    if 'Policy' in topic_attributes:
        try:
            policy = json.loads(topic_attributes['Policy'])
        except json.JSONDecodeError:
            policy = topic_attributes['Policy']
    
    # Check if topic is FIFO
    is_fifo = topic_name.endswith('.fifo')
    
    # Get delivery policy if available
    delivery_policy = None
    if 'DeliveryPolicy' in topic_attributes:
        try:
            delivery_policy = json.loads(topic_attributes['DeliveryPolicy'])
        except json.JSONDecodeError:
            delivery_policy = topic_attributes['DeliveryPolicy']
    
    # Compile all topic details
    topic_details = {
        "TopicArn": topic_arn,
        "TopicName": topic_name,
        "Attributes": topic_attributes,
        "Subscriptions": detailed_subscriptions,
        "Tags": tags,
        "Policy": policy,
        "IsFifo": is_fifo,
        "DeliveryPolicy": delivery_policy
    }
    
    # If it's a FIFO topic, include additional FIFO properties
    if is_fifo and 'FifoTopic' in topic_attributes:
        topic_details["FifoProperties"] = {
            "FifoTopic": topic_attributes.get('FifoTopic'),
            "ContentBasedDeduplication": topic_attributes.get('ContentBasedDeduplication')
        }
    
    # Check for dead-letter queue configuration
    if 'RedrivePolicy' in topic_attributes:
        try:
            redrive_policy = json.loads(topic_attributes['RedrivePolicy'])
            topic_details["DeadLetterQueue"] = redrive_policy
        except json.JSONDecodeError:
            topic_details["DeadLetterQueue"] = topic_attributes['RedrivePolicy']
    
    return topic_details


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python fetch_aws_config.py <ApplicationShortName> <output_file> <env_index>")
        sys.exit(1)

    ApplicationShortName = sys.argv[1]
    output_file = sys.argv[2]
    env_index = int(sys.argv[3]) if len(sys.argv) > 3 else None

    try:
        # Load environment configuration
        env_config = load_env_config(env_index) if env_index is not None else None
        output_data = {}
        print("Env config: ", env_config)

        if env_config:
            # Fetch ECS configurations if ecs array is not empty
            ecs_clusters = env_config.get('ecs', [])
            if ecs_clusters:
                output_data['ecs'] = fetch_ecs_service_config(ecs_clusters, use_custom_identifier=True)
            else:
                matching_clusters = find_team_cluster(team_tag_key='ApplicationShortName', team_tag_value=ApplicationShortName)
                ecs_clusters = [{"clusterName": cluster_name} for cluster_name, _ in matching_clusters]
                output_data['ecs'] = fetch_ecs_service_config(ecs_clusters, use_custom_identifier=False) if matching_clusters else {}
            
            # Fetch RDS configurations if rds array is not empty
            rds_instances = env_config.get('rds', [])
            if rds_instances:
                output_data['rds'] = fetch_rds_config(rds_instances, use_instance_ids=True)
            else:
                output_data['rds'] = fetch_rds_config(ApplicationShortName, use_instance_ids=False)
            
            # Fetch Lambda configurations if lambda array is not empty
            lambda_functions = env_config.get('lambda', [])
            if lambda_functions:
                output_data['lambda'] = fetch_lambda_config(lambda_functions, use_function_names=True)
            else:
                output_data['lambda'] = fetch_lambda_config(ApplicationShortName, use_function_names=False)

            # Fetch Parameter Store configurations if parameterStore prefixes are provided
            parameter_store_prefixes = env_config.get('parameterStore')
            if parameter_store_prefixes:
                output_data['parameterStore'] = fetch_parameter_store_config(parameter_store_prefixes, use_custom_names=True)
            else:
                output_data['parameterStore'] = fetch_parameter_store_config([ApplicationShortName], use_custom_names=False)
            
            # Fetch EC2 load balancer configurations if elb array is not empty
            elb_names = env_config.get('elb', [])
            if elb_names:
                output_data['elb'] = fetch_elb_config(elb_names, use_lb_names=True)
            else:
                output_data['elb'] = fetch_elb_config(ApplicationShortName, use_lb_names=False)
            
            # Fetch SQS configurations if sqs array is not empty
            sqs_queues = env_config.get('sqs', [])
            if sqs_queues:
                output_data['sqs'] = fetch_sqs_config(sqs_queues, ApplicationShortName)
            else:
                output_data['sqs'] = fetch_sqs_config([], ApplicationShortName)
                
            # Fetch SNS configurations if sns array is not empty
            sns_topics = env_config.get('sns', [])
            if sns_topics:
                output_data['sns'] = fetch_sns_config(sns_topics, use_topic_names=True)
            else:
                output_data['sns'] = fetch_sns_config(ApplicationShortName, use_topic_names=False)
        else:
            print("Env configs not found, fetching configs by ApplicationShortName: ", ApplicationShortName)
            # Fall back to original behavior
            matching_clusters = find_team_cluster(team_tag_key='ApplicationShortName', team_tag_value=ApplicationShortName)
            ecs_clusters = [{"clusterName": cluster_name} for cluster_name, _ in matching_clusters]
            output_data = {
                'ecs': fetch_ecs_service_config(ecs_clusters, use_custom_identifier=False) if matching_clusters else {},
                'rds': fetch_rds_config(ApplicationShortName, use_instance_ids=False),
                'lambda': fetch_lambda_config(ApplicationShortName, use_function_names=False),
                'parameterStore': fetch_parameter_store_config([ApplicationShortName], use_custom_names=False),
                'elb': fetch_elb_config(ApplicationShortName, use_lb_names=False),
                'sqs': fetch_sqs_config([], ApplicationShortName),
                'sns': fetch_sns_config(ApplicationShortName, use_topic_names=False)
            }

        # Write to the output file
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=4, cls=DateTimeEncoder)

        print(f"All configurations successfully written to {output_file}")

    except Exception as e:
        print(f"Error fetching configurations: {e}")
        sys.exit(1)