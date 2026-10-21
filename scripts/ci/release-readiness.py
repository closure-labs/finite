#!/usr/bin/env python3
"""Skip unready release work before tool installation or product downloads."""
import argparse
import json
import os
import re
from pathlib import Path

from github_api import get_json
from release_readiness import PREFIX, eligible_build, release_status, root_version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-selection', action='store_true')
    parser.add_argument('--build-run')
    args = parser.parse_args()
    status = release_status(root_version(), bot=None if args.build_selection else os.environ.get('FINITE_REVIEW_BOT_LOGIN'))
    ready = status['state'] == 'unprepared'
    if ready and args.build_run:
        if not re.fullmatch('[1-9][0-9]*', args.build_run):
            raise ValueError('Invalid build producer')
        run = get_json(PREFIX + '/actions/runs/' + args.build_run)
        jobs = get_json(PREFIX + f'/actions/runs/{args.build_run}/attempts/{run["run_attempt"]}/jobs?per_page=100')
        artifacts = get_json(PREFIX + f'/actions/runs/{args.build_run}/artifacts?per_page=100')
        if (jobs['total_count'] > 100 or artifacts['total_count'] > 100
                or not eligible_build(run, jobs['jobs'], artifacts['artifacts'], os.environ['GITHUB_SHA'])):
            raise ValueError('Release needs both successful same-revision qualifications and preserved ISOs')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        print('ready=' + str(ready).lower(), file=output)
        if args.build_selection and ready:
            print('checks=true\nnix=false\nprofiles=["finite","finite-dev"]', file=output)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('### Release readiness\n\n' + status['reason'] + '\n')
    print(json.dumps(status))
    if not args.build_selection and status['state'] == 'recovery':
        raise ValueError(status['reason'])


if __name__ == '__main__':
    main()
