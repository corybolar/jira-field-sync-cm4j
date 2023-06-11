""" Synchronize a custom JIRA field with a list of options from file """

import argparse
import copy
import fileinput
import logging
import sys

import requests

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

parser = argparse.ArgumentParser()
parser.add_argument('--jira-base-url', type=str, required=True, help='Base URL of JIRA instance')
parser.add_argument('--api-key', type=str, required=True, help='JIRA API Key')
parser.add_argument('--field-id', type=str, required=True, help='Custom field id (CM4J)')
parser.add_argument('--debug', action='store_true', help='Verbose logging')
parser.add_argument('--silent', action='store_true', help='Silent logging')
#parser.add_argument('--option-file-path', type=str, required=True,
#                    help='Path to file containing list of options')
parser.add_argument('options', nargs='*',
                    help='Path to file(s) containing list of options')

parser.add_argument('--project-slug', type=str, required=True, help='JIRA project slug')
parser.add_argument('--static-options', nargs='+',
                    help="Static list of options to append to selection. Space delimited",
                    default='Other')
parser.add_argument('--dry-run', '-n', action='store_true', help='Skip making changes')
args = parser.parse_args()

if args.debug:
    logger.setLevel(logging.DEBUG)
if args.silent:
    logger.setLevel(logging.CRITICAL)

session = requests.Session()
session.headers.update({
    'Authorization': f'Bearer: {args.api_key}'
})

CONTEXT_MANAGER_PATH = '/plugins/servlet/com.easesolutions.jira.plugins.contextmanager/projectadmin'
base_url = args.jira_base_url + CONTEXT_MANAGER_PATH

field_id = args.field_id

static_opts = [args.static_options] if isinstance(args.static_options, str) else args.static_options

def read_input() -> dict:
    """Read option list from files or stdin if no files are passed"""
    option_list = copy.deepcopy(static_opts)
    for line in fileinput.input(files=args.options if len(args.options) > 0 else ('-', )):
        if line.strip():
            option_list.append(line.strip())

    if len(option_list) == len(static_opts):
        logger.critical("No options read from input!")
        sys.exit(1)
    return option_list

def is_error(res: requests.Response):
    """Check if error"""
    try:
        res.raise_for_status()
    except requests.RequestException as exc:
        logger.critical("Requests error!")
        logger.critical("URL: %s", res.request.url)
        logger.critical("Body: %s", res.request.body)
        logger.critical("Code: %s", res.status_code)
        logger.critical("Response: %s", res.text)
        raise exc

def get_options() -> dict:
    """Retrieve list of existing field options from JIRA"""
    params = {
        'op': 'movePositions',
        'projectKey': args.project_slug,
    }

    json_data = {
        'customFieldId': field_id,
        'positions': {},
    }

    response = session.post(base_url, params=params, json=json_data)
    is_error(response)
    res = response.json()
    return res['data'][0]['context']['values']

def get_option_id(value: str):
    """Retrieve id of field with name value"""
    option_list = get_options()
    for option in option_list:
        if option.get('value') == value:
            return option.get('optionId')
    return None

def disable_option(option_id: str) -> dict:
    """Disable a field by id"""
    params = {
        'op': 'updateEnabled',
        'projectKey': args.project_slug,
    }
    # isDisabled is inverted in the API...
    json_data = {
        'customFieldId': field_id,
        'isDisabled': False,
        'optionId': option_id,
    }
    logger.debug("Disabling %s", option_id)
    if args.dry_run:
        return None
    response = session.post(base_url, params=params, json=json_data)
    is_error(response)
    return response.json()['data'][0]['context']['values']

def enable_option(option_id: str) -> dict:
    """Enable a field by id"""
    params = {
        'op': 'updateEnabled',
        'projectKey': args.project_slug,
    }
    # isDisabled is inverted in the API...
    json_data = {
        'customFieldId': field_id,
        'isDisabled': True,
        'optionId': option_id,
    }
    logger.debug("Enabling %s", option_id)
    if args.dry_run:
        return None
    response = session.post(base_url, params=params, json=json_data)
    is_error(response)
    return response.json()['data'][0]['context']['values']

def add_option(value: str, position: str) -> dict:
    """Add new field option to JIRA"""
    params = {
        'op': 'addOption',
        'projectKey': args.project_slug,
    }
    json_data = {
        'customFieldId': field_id,
        'value': value,
        'position': position
    }
    logger.info("Adding %s to position %s", value, position)
    if args.dry_run:
        return None
    response = session.post(base_url, params=params, json=json_data)
    is_error(response)
    return response.json()['data'][0]['context']['values']

def move_option(positions: dict) -> dict:
    """Reorder field options by position dictionary"""
    params = {
        'op': 'movePositions',
        'projectKey': args.project_slug,
    }

    json_data = {
        'customFieldId': field_id,
        'positions': positions,
    }
    logger.debug("Reordering positions: %s", positions)
    if args.dry_run:
        return None
    response = session.post(base_url, params=params, json=json_data)
    is_error(response)
    return response.json()['data'][0]['context']['values']

# pylint: disable=too-many-locals
def main():
    """Main function"""
    current_options_json = get_options()
    current_options = [x.get('value') for x in current_options_json]

    logger.debug("Current JIRA List: %s", current_options)


    option_list = read_input()
    jira_options = set(current_options)
    file_options = set(option_list)
    logger.info("Existing JIRA options: %s", jira_options)
    logger.info("New options: %s", file_options)

    missing = list(sorted(jira_options - file_options))
    logger.info("Removals: %s", missing)

    additions = list(sorted(file_options - jira_options))
    logger.info("Additions: %s", additions)

    # Disable options from missing
    for opt in missing:
        for copt in current_options_json:
            if opt == copt.get('value'):
                logger.info("Disabling option: %s", {'name': opt, 'id': copt.get('optionId')})
                disable_option(copt.get('optionId'))
                break

    # Add options from additions
    for idx,opt in enumerate(additions):
        add_option(opt, str(idx))

    # Enable all options in source of truth list
    for opt in option_list:
        opt_id = get_option_id(opt)
        logger.info("Enabling option: %s", {'name': opt, 'id': opt_id})
        enable_option(opt_id)

    # Reorder option list in JIRA alphabetically with static options appended to the end
    current_options_json = get_options()

    unsorted_opt_list = [opt for opt in current_options_json if opt['value'] not in static_opts]
    sorted_opt_list = sorted(unsorted_opt_list, key=lambda opt: opt['value'])

    logger.info("Sorted option list: %s", [opt['value'] for opt in sorted_opt_list])

    positions = {opt.get('optionId'): str(idx+1) for idx,opt in enumerate(sorted_opt_list)}

    max_pos = len(positions)
    for idx, opt in enumerate(static_opts):
        positions[get_option_id(opt)] = str(max_pos + idx + 1)

    move_option(positions)

    logger.info("Success")

if __name__ == '__main__':
    main()
