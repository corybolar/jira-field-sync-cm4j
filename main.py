import requests
import json
import logging
import copy
import argparse
import sys

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

parser = argparse.ArgumentParser()
parser.add_argument('--jira-base-url', type=str, required=True, help='Base URL of JIRA instance')
parser.add_argument('--api-key', type=str, required=True, help='JIRA API Key')
parser.add_argument('--field-id', type=str, required=True, help='Custom field id (CM4J)')
parser.add_argument('--debug', action='store_true', help='Verbose logging')
parser.add_argument('--silent', action='store_true', help='Silent logging')
parser.add_argument('--consumer-file-path', type=str, required=True, help='Path to current list of consumers')
parser.add_argument('--project-slug', type=str, required=True, help='JIRA project slug')
parser.add_argument('--static-consumers', nargs='+', help="Static list of consumers to append to selection. Space delimited", default='Other')
args = parser.parse_args()

if args.debug:
    logger.setLevel(logging.DEBUG)
if args.silent:
    logger.setLevel(logging.CRITICAL)

headers = {
    'Authorization': f'Bearer: {args.api_key}'
}

base_url = args.jira_base_url + '/plugins/servlet/com.easesolutions.jira.plugins.contextmanager/projectadmin'

fieldId = args.field_id

static_consumers = [args.static_consumers] if isinstance(args.static_consumers, str) else args.static_consumers

def getConsumers():
    params = {
        'op': 'movePositions',
        'projectKey': args.project_slug,
    }

    json_data = {
        'customFieldId': fieldId,
        'positions': {},
    }

    response = requests.post(base_url, params=params, headers=headers, json=json_data)
    response.raise_for_status()
    res = response.json()
    return res['data'][0]['context']['values']

def getConsumerId(value):
    clist = getConsumers()
    for x in clist:
        if x.get('value') == value:
            return x.get('optionId')
    return None

def disableConsumer(optionId):
    params = {
        'op': 'updateEnabled',
        'projectKey': args.project_slug,
    }
    # isDisabled is inverted in the API...
    json_data = {
        'customFieldId': fieldId,
        'isDisabled': False,
        'optionId': optionId,
    }
    logger.info("Disabling %s", optionId)
    response = requests.post(base_url, params=params, headers=headers, json=json_data)
    response.raise_for_status()
    return response.json()['data'][0]['context']['values']

def enableConsumer(optionId):
    params = {
        'op': 'updateEnabled',
        'projectKey': args.project_slug,
    }
    # isDisabled is inverted in the API...
    json_data = {
        'customFieldId': fieldId,
        'isDisabled': True,
        'optionId': optionId,
    }
    logger.info("Enabling %s", optionId)
    response = requests.post(base_url, params=params, headers=headers, json=json_data)
    response.raise_for_status()
    return response.json()['data'][0]['context']['values']

def addConsumer(value, position):
    params = {
        'op': 'addOption',
        'projectKey': args.project_slug,
    }
    json_data = {
        'customFieldId': fieldId,
        'value': value,
        'position': str(position)
    }
    logger.info("Adding %s to position ", value, position)
    response = requests.post(base_url, params=params, headers=headers, json=json_data)
    response.raise_for_status()
    return response.json()['data'][0]['context']['values']

def moveConsumers(positions):
    params = {
        'op': 'movePositions',
        'projectKey': args.project_slug,
    }

    json_data = {
        'customFieldId': fieldId,
        'positions': positions,
    }
    logger.info("Reordering positions: %s", positions)
    response = requests.post(base_url, params=params, headers=headers, json=json_data)
    response.raise_for_status()
    res = response.json()
    return res['data'][0]['context']['values']

def main():
    current_consumers_json = getConsumers()
    current_consumers = [x.get('value') for x in current_consumers_json]

    logger.debug("Current JIRA List: %s", current_consumers)

    consumer_list = copy.deepcopy(static_consumers)
    with open(args.consumer_file_path, 'r') as f:
        for line in f:
            consumer_list.append(line.strip())

    jira_consumers = set(current_consumers)
    portal_consumers = set(consumer_list)
    logger.info("Existing JIRA Consumers: %s", jira_consumers)
    logger.info("Portal Consumers: %s", portal_consumers)

    missing = list(sorted(jira_consumers - portal_consumers))
    logger.info("Removals: %s", missing)
    for consumer in missing:
        for x in current_consumers_json:
            if consumer == x.get('value'):
                logger.info("Disabling consumer: %s id: %s", consumer, x.get('optionId'))
                disableConsumer(x.get('optionId'))
                break

    additions = list(sorted(portal_consumers - jira_consumers))
    for index,consumer in enumerate(additions):
        addConsumer(consumer, index)

    for consumer in consumer_list:
        enableConsumer(getConsumerId(consumer))

    logger.info("Additions: %s", additions)

    current_consumers_json = getConsumers()

    unsorted_consumers_list = [x for x in current_consumers_json if x['value'] not in static_consumers]
    sorted_consumer_list = sorted(unsorted_consumers_list, key=lambda x: x['value'])

    logger.info("Sorted Consumer List: %s", sorted_consumer_list)

    positions = {x.get('optionId'): str(idx+1) for idx,x in enumerate(sorted_consumer_list)}

    max_pos = len(positions)
    for idx, x in enumerate(static_consumers):
        positions[getConsumerId(x)] = str(max_pos + idx + 1)

    moveConsumers(positions)

    logger.info("Success")

if __name__ == '__main__':
    main()

